module sable_tx #(
    parameter integer TIMEOUT_CYCLES = 4096,
    parameter integer MAX_RETRIES = 4,
    parameter integer GENERATION_BITS = 24
) (
    input wire clk, rst,
    input wire [31:0] session_id,
    input wire s_msg_valid,
    output wire s_msg_ready,
    input wire [63:0] s_msg_data,
    input wire [7:0] s_msg_keep,
    input wire s_msg_first, s_msg_last,
    input wire [1:0] s_msg_stream,
    input wire [12:0] s_msg_len,
    output wire m_status_valid,
    input wire m_status_ready,
    output wire [1:0] m_status_stream, m_status_code,
    output wire [3:0] tx_failed, session_exhausted,
    output wire m_data_valid,
    input wire m_data_ready,
    output wire [63:0] m_data_data,
    output wire [7:0] m_data_keep,
    output wire m_data_first, m_data_last,
    input wire s_ack_valid,
    output wire s_ack_ready,
    input wire [63:0] s_ack_data,
    input wire [7:0] s_ack_keep,
    input wire s_ack_first, s_ack_last
);
    localparam [32:0] ID_LIMIT = 33'd1 << (8 + GENERATION_BITS);
    initial begin
        if (TIMEOUT_CYCLES < 1 || TIMEOUT_CYCLES > 65535)
            $fatal(1, "PARAMETER ERROR: TIMEOUT_CYCLES");
        if (MAX_RETRIES < 0 || MAX_RETRIES > 15)
            $fatal(1, "PARAMETER ERROR: MAX_RETRIES");
        if (GENERATION_BITS < 1 || GENERATION_BITS > 24)
            $fatal(1, "PARAMETER ERROR: GENERATION_BITS");
    end

    function automatic [31:0] crc_word;
        input [31:0] crc;
        input [63:0] data;
        input [7:0] keep;
        reg [31:0] c;
        integer b, n;
        begin
            c = crc;
            for (b=0; b<8; b=b+1)
                if (keep[b]) begin
                    c = c ^ {24'b0, data[b*8 +: 8]};
                    for (n=0; n<8; n=n+1)
                        if (c[0]) c = (c >> 1) ^ 32'h82f63b78;
                        else c = c >> 1;
                end
            crc_word = c;
        end
    endfunction
    function automatic [7:0] byte_keep;
        input integer count;
        begin
            if (count >= 8) byte_keep = 8'hff;
            else byte_keep = (8'h01 << count) - 1'b1;
        end
    endfunction
    function automatic [63:0] clean_word;
        input [63:0] data;
        input [7:0] keep;
        integer b;
        begin
            clean_word=0;
            for (b=0;b<8;b=b+1)
                if (keep[b]) clean_word[b*8 +: 8]=data[b*8 +: 8];
        end
    endfunction

    reg [31:0] session;
    reg [63:0] message_mem [0:2047];
    reg [3:0] busy, collected, terminal, failed, exhausted;
    reg [12:0] msg_len [0:3];
    reg [9:0] input_word [0:3];
    reg [4:0] packets [0:3], next_new [0:3], oldest [0:3];
    reg [31:0] base [0:3];
    reg [32:0] allocation [0:3];
    reg [15:0] sent [0:3], acknowledged [0:3];
    reg [31:0] slot_live;
    reg [3:0] slot_packet [0:31];
    reg [15:0] timer [0:31];
    reg [3:0] retries [0:31];
    reg [31:0] overdue;
    reg [3:0] mailbox;
    reg [1:0] result [0:3];
    reg status_v;
    reg [1:0] status_s, status_c, status_rr;

    reg sending;
    reg [1:0] frame_stream, data_rr;
    reg [3:0] frame_packet;
    reg [31:0] frame_id;
    reg [12:0] frame_len;
    reg [8:0] frame_payload;
    reg [12:0] frame_offset;
    reg [5:0] frame_word;
    reg [2:0] phase;
    reg [31:0] frame_crc;
    reg data_v, data_f, data_l;
    reg [63:0] data_d;
    reg [7:0] data_k;

    reg [2:0] ack_phase;
    reg ack_good;
    reg [63:0] ack_h0, ack_h1;
    reg [31:0] ack_crc;
    wire [1:0] ack_stream = ack_h0[33:32];
    wire [31:0] ack_id = ack_h1[63:32];
    wire [31:0] ack_relative = ack_id - base[ack_stream];
    wire ack_frame_ok = s_ack_valid && !s_ack_first && s_ack_last &&
        ack_phase==3 && ack_good && s_ack_keep==8'h0f &&
        s_ack_data[63:32]==0 && s_ack_data[31:0]==~ack_crc;
    wire ack_match = ack_frame_ok && busy[ack_stream] &&
        !terminal[ack_stream] && ack_id >= base[ack_stream] &&
        ack_relative < {27'b0,packets[ack_stream]} &&
        sent[ack_stream][ack_relative[3:0]] &&
        !acknowledged[ack_stream][ack_relative[3:0]];

    wire [5:0] offered_packets = ({1'b0,s_msg_len} + 14'd255) >> 8;
    wire enough_ids = allocation[s_msg_stream] + {27'b0,offered_packets} <= ID_LIMIT;
    wire stream_draining = sending && frame_stream==s_msg_stream;
    assign s_msg_ready = !rst && !failed[s_msg_stream] && !exhausted[s_msg_stream] &&
        ((busy[s_msg_stream] && !collected[s_msg_stream] && !terminal[s_msg_stream]) ||
         (!busy[s_msg_stream] && !stream_draining && enough_ids));
    assign m_status_valid = !rst && status_v;
    assign m_status_stream = rst ? 2'b0 : status_s;
    assign m_status_code = rst ? 2'b0 : status_c;
    assign tx_failed = rst ? 4'b0 : failed;
    assign session_exhausted = rst ? 4'b0 : exhausted;
    assign m_data_valid = !rst && data_v;
    assign m_data_data = rst ? 64'b0 : data_d;
    assign m_data_keep = rst ? 8'b0 : data_k;
    assign m_data_first = !rst && data_f;
    assign m_data_last = !rst && data_l;
    assign s_ack_ready = !rst;

    integer i, j, f, q, idx, candidate_stream, candidate_packet, candidate_slot;
    integer status_choice, remaining;
    reg candidate_retry, found, found_packet;
    reg [63:0] build_data;
    reg [7:0] build_keep;

    always @* begin
        candidate_stream=-1;
        candidate_packet=0;
        candidate_slot=0;
        candidate_retry=0;
        found=0;
        found_packet=0;
        f=0;
        q=0;
        idx=0;
        for (i=0;i<4;i=i+1) begin
            f=(data_rr+i)&3;
            if (!found && busy[f] && collected[f] && !terminal[f]) begin
                found_packet=0;
                for (j=0;j<16;j=j+1) begin
                    q=j;
                    idx=f*8+(q&7);
                    if (!found_packet && q>=oldest[f] && q<next_new[f] &&
                        slot_live[idx] && slot_packet[idx]==q &&
                        sent[f][q] && !acknowledged[f][q] && overdue[idx] &&
                        !(ack_match && ack_stream==f && ack_relative==q)) begin
                        found_packet=1;
                        found=1;
                        candidate_stream=f;
                        candidate_packet=q;
                        candidate_slot=idx;
                        candidate_retry=1;
                    end
                end
                if (!found_packet && next_new[f]<packets[f] &&
                    next_new[f]-oldest[f]<8) begin
                    found=1;
                    candidate_stream=f;
                    candidate_packet=next_new[f];
                    candidate_slot=f*8+(next_new[f]&7);
                end
            end
        end
        status_choice=-1;
        for (i=0;i<4;i=i+1) begin
            f=(status_rr+i)&3;
            if (status_choice<0 && mailbox[f]) status_choice=f;
        end
    end

    always @* begin
        build_data=0;
        build_keep=8'hff;
        remaining=0;
        case (phase)
            0: begin
                build_data[31:0]=32'h00014253;
                build_data[39:32]={6'b0,frame_stream};
                build_data[40]=(frame_offset==0);
                build_data[41]=(frame_offset+frame_payload==frame_len);
                build_data[63:48]={7'b0,frame_payload};
            end
            1: build_data={frame_id,session};
            2: begin
                build_data[15:0]={3'b0,frame_len};
                build_data[31:16]={3'b0,frame_offset};
            end
            3: begin
                remaining=frame_payload-frame_word*8;
                build_keep=byte_keep(remaining);
                build_data=clean_word(message_mem[frame_stream*512+
                    (frame_offset>>3)+frame_word],build_keep);
            end
            4: begin
                build_keep=8'h0f;
                build_data={32'b0,~frame_crc};
            end
            default: begin build_data=0; build_keep=0; end
        endcase
    end

    integer a, b, sp;
    always @(posedge clk) begin
        if (rst) begin
            session<=session_id;
            busy<=0; collected<=0; terminal<=0; failed<=0; exhausted<=0;
            slot_live<=0; overdue<=0; mailbox<=0;
            status_v<=0; status_s<=0; status_c<=0; status_rr<=0;
            sending<=0; frame_stream<=0; frame_packet<=0; frame_id<=0;
            frame_len<=0; frame_payload<=0; frame_offset<=0;
            frame_word<=0; phase<=0; frame_crc<=32'hffffffff; data_rr<=0;
            data_v<=0; data_d<=0; data_k<=0; data_f<=0; data_l<=0;
            ack_phase<=0; ack_good<=0; ack_h0<=0; ack_h1<=0;
            ack_crc<=32'hffffffff;
            for (a=0;a<4;a=a+1) begin
                msg_len[a]<=0; input_word[a]<=0; packets[a]<=0;
                next_new[a]<=0; oldest[a]<=0; base[a]<=0; allocation[a]<=0;
                sent[a]<=0; acknowledged[a]<=0; result[a]<=0;
            end
            for (a=0;a<32;a=a+1) begin
                slot_packet[a]<=0; timer[a]<=0; retries[a]<=0;
            end
        end else begin
            if (s_msg_valid && s_msg_first && !busy[s_msg_stream] &&
                !stream_draining && !failed[s_msg_stream] &&
                !enough_ids) exhausted[s_msg_stream]<=1;
            if (s_msg_valid && s_msg_ready) begin
                if (!busy[s_msg_stream]) begin
                    busy[s_msg_stream]<=1;
                    collected[s_msg_stream]<=s_msg_last;
                    terminal[s_msg_stream]<=0;
                    msg_len[s_msg_stream]<=s_msg_len;
                    packets[s_msg_stream]<=offered_packets[4:0];
                    base[s_msg_stream]<=allocation[s_msg_stream][31:0];
                    allocation[s_msg_stream]<=allocation[s_msg_stream]+
                        {27'b0,offered_packets};
                    next_new[s_msg_stream]<=0;
                    oldest[s_msg_stream]<=0;
                    sent[s_msg_stream]<=0;
                    acknowledged[s_msg_stream]<=0;
                    input_word[s_msg_stream]<=1;
                    message_mem[s_msg_stream*512]<=clean_word(s_msg_data,s_msg_keep);
                end else begin
                    message_mem[s_msg_stream*512+input_word[s_msg_stream]]<=
                        clean_word(s_msg_data,s_msg_keep);
                    input_word[s_msg_stream]<=input_word[s_msg_stream]+1'b1;
                    if (s_msg_last) collected[s_msg_stream]<=1;
                end
            end

            if (s_ack_valid) begin
                if (s_ack_first) begin
                    ack_h0<=s_ack_data;
                    ack_crc<=crc_word(32'hffffffff,s_ack_data,8'hff);
                    ack_good<=!s_ack_last && s_ack_keep==8'hff &&
                        s_ack_data[31:0]==32'h01014253 &&
                        s_ack_data[39:34]==0 && s_ack_data[63:40]==0;
                    if (s_ack_last) ack_phase<=0;
                    else ack_phase<=1;
                end else if (ack_phase!=0) begin
                    if (ack_phase==1) begin
                        ack_h1<=s_ack_data;
                        ack_crc<=crc_word(ack_crc,s_ack_data,8'hff);
                        ack_good<=ack_good && !s_ack_last && s_ack_keep==8'hff &&
                            s_ack_data[31:0]==session &&
                            ({1'b0,s_ack_data[63:32]} < ID_LIMIT);
                        ack_phase<=2;
                    end else if (ack_phase==2) begin
                        ack_crc<=crc_word(ack_crc,s_ack_data,8'hff);
                        ack_good<=ack_good && !s_ack_last &&
                            s_ack_keep==8'hff && s_ack_data==0;
                        ack_phase<=3;
                    end else begin
                        ack_good<=0;
                        ack_phase<=4;
                    end
                    if (s_ack_last) begin ack_phase<=0; ack_good<=0; end
                end
            end
            if (ack_match)
                acknowledged[ack_stream][ack_relative[3:0]]<=1;

            for (a=0;a<4;a=a+1) begin
                if (busy[a] && collected[a] && !terminal[a]) begin
                    if (oldest[a]<packets[a] && acknowledged[a][oldest[a][3:0]])
                        oldest[a]<=oldest[a]+1'b1;
                    if (oldest[a]==packets[a]) begin
                        terminal[a]<=1;
                        mailbox[a]<=1;
                        result[a]<=0;
                    end
                end
                for (b=0;b<8;b=b+1) begin
                    sp=a*8+b;
                    if (slot_live[sp] && !terminal[a] &&
                        sent[a][slot_packet[sp]] &&
                        !acknowledged[a][slot_packet[sp]] &&
                        !(sending && frame_stream==a &&
                          frame_packet==slot_packet[sp]) &&
                        !(ack_match && ack_stream==a &&
                          ack_relative==slot_packet[sp])) begin
                        if (!overdue[sp]) begin
                            if (timer[sp]>=TIMEOUT_CYCLES-1) overdue[sp]<=1;
                            else timer[sp]<=timer[sp]+1'b1;
                        end
                    end
                end
            end

            if (!status_v && status_choice>=0) begin
                status_v<=1;
                status_s<=status_choice[1:0];
                status_c<=result[status_choice];
            end else if (status_v && m_status_ready) begin
                status_v<=0; status_s<=0; status_c<=0;
                mailbox[status_s]<=0;
                busy[status_s]<=0;
                collected[status_s]<=0;
                status_rr<=status_s+1'b1;
            end

            if (!sending && candidate_stream>=0) begin
                if (candidate_retry && retries[candidate_slot]>=MAX_RETRIES) begin
                    terminal[candidate_stream]<=1;
                    failed[candidate_stream]<=1;
                    mailbox[candidate_stream]<=1;
                    result[candidate_stream]<=1;
                    data_rr<=candidate_stream[1:0]+1'b1;
                end else begin
                    sending<=1;
                    frame_stream<=candidate_stream[1:0];
                    frame_packet<=candidate_packet[3:0];
                    frame_id<=base[candidate_stream]+candidate_packet;
                    frame_len<=msg_len[candidate_stream];
                    frame_offset<=candidate_packet*256;
                    if (msg_len[candidate_stream]-candidate_packet*256>=256)
                        frame_payload<=256;
                    else frame_payload<=msg_len[candidate_stream]-candidate_packet*256;
                    frame_word<=0;
                    phase<=0;
                    frame_crc<=32'hffffffff;
                    data_rr<=candidate_stream[1:0]+1'b1;
                    overdue[candidate_slot]<=0;
                    timer[candidate_slot]<=0;
                    if (candidate_retry)
                        retries[candidate_slot]<=retries[candidate_slot]+1'b1;
                    else begin
                        slot_live[candidate_slot]<=1;
                        slot_packet[candidate_slot]<=candidate_packet[3:0];
                        retries[candidate_slot]<=0;
                        next_new[candidate_stream]<=next_new[candidate_stream]+1'b1;
                    end
                end
            end
            if (sending && !data_v) begin
                data_v<=1;
                data_d<=build_data;
                data_k<=build_keep;
                data_f<=(phase==0);
                data_l<=(phase==4);
            end else if (data_v && m_data_ready) begin
                data_v<=0; data_d<=0; data_k<=0; data_f<=0; data_l<=0;
                if (phase!=4) frame_crc<=crc_word(frame_crc,data_d,data_k);
                case (phase)
                    0: phase<=1;
                    1: phase<=2;
                    2: phase<=3;
                    3: begin
                        if ((frame_word+1)*8>=frame_payload) phase<=4;
                        else frame_word<=frame_word+1'b1;
                    end
                    4: begin
                        sending<=0;
                        if (!terminal[frame_stream] &&
                            !acknowledged[frame_stream][frame_packet]) begin
                            sent[frame_stream][frame_packet]<=1;
                            timer[frame_stream*8+(frame_packet&7)]<=0;
                            overdue[frame_stream*8+(frame_packet&7)]<=0;
                        end
                    end
                    default: phase<=0;
                endcase
            end
        end
    end
endmodule

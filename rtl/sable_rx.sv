module sable_rx #(
    parameter integer GENERATION_BITS = 24
) (
    input wire clk, rst,
    input wire [31:0] session_id,
    input wire s_data_valid,
    output wire s_data_ready,
    input wire [63:0] s_data_data,
    input wire [7:0] s_data_keep,
    input wire s_data_first, s_data_last,
    output wire m_msg_valid,
    input wire m_msg_ready,
    output wire [63:0] m_msg_data,
    output wire [7:0] m_msg_keep,
    output wire m_msg_first, m_msg_last,
    output wire [1:0] m_msg_stream,
    output wire [12:0] m_msg_len,
    output wire m_ack_valid,
    input wire m_ack_ready,
    output wire [63:0] m_ack_data,
    output wire [7:0] m_ack_keep,
    output wire m_ack_first, m_ack_last
);
    localparam [32:0] ID_LIMIT = 33'd1 << (8+GENERATION_BITS);
    initial begin
        if (GENERATION_BITS < 1 || GENERATION_BITS > 24)
            $fatal(1, "PARAMETER ERROR: GENERATION_BITS");
    end
    function automatic [31:0] crc_word;
        input [31:0] crc;
        input [63:0] data;
        input [7:0] keep;
        reg [31:0] c;
        integer b,n;
        begin
            c=crc;
            for (b=0;b<8;b=b+1)
                if (keep[b]) begin
                    c=c ^ {24'b0,data[b*8 +: 8]};
                    for (n=0;n<8;n=n+1)
                        if (c[0]) c=(c>>1)^32'h82f63b78;
                        else c=c>>1;
                end
            crc_word=c;
        end
    endfunction
    function automatic [7:0] byte_keep;
        input integer count;
        begin
            if (count>=8) byte_keep=8'hff;
            else byte_keep=(8'h01<<count)-1'b1;
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
    reg [63:0] staging [0:31];
    reg [63:0] packet_mem [0:1023];
    reg [63:0] message_mem [0:2047];
    reg [3:0] active, complete;
    reg [32:0] receive_base [0:3];
    reg [12:0] message_len [0:3];
    reg [4:0] message_packets [0:3], copied [0:3];
    reg [8:0] output_word [0:3];
    reg [31:0] slot_valid;
    reg [3:0] slot_index [0:31];
    reg [8:0] slot_bytes [0:31];

    // A frame is validated in staging before any persistent ownership changes.
    reg [3:0] parse_phase;
    reg parse_good;
    reg [63:0] h0,h1,h2;
    reg [31:0] parse_crc;
    reg [5:0] payload_word, commit_word;
    wire [1:0] incoming_stream=h0[33:32];
    wire [31:0] incoming_id=h1[63:32];
    wire [8:0] incoming_bytes=h0[56:48];
    wire [12:0] incoming_len=h2[12:0];
    wire [3:0] incoming_packet=h2[27:24];
    wire [4:0] incoming_packets=({1'b0,incoming_len}+14'd255)>>8;
    wire [5:0] incoming_words=({1'b0,incoming_bytes}+10'd7)>>3;
    wire [32:0] incoming_identity={1'b0,incoming_id};
    wire [5:0] payload_expected_words=({1'b0,incoming_bytes}+10'd7)>>3;
    wire [7:0] payload_keep=byte_keep(incoming_bytes-payload_word*8);
    wire structural_h2 = s_data_data[63:32]==0 &&
        s_data_data[15:13]==0 && s_data_data[31:28]==0 &&
        s_data_data[23:16]==0 &&
        s_data_data[12:0]>=1 && s_data_data[12:0]<=4096 &&
        {3'b0,s_data_data[12:0]} > s_data_data[31:16] &&
        h0[40]==(s_data_data[31:16]==0) &&
        h0[41]==(s_data_data[31:16]+{7'b0,incoming_bytes}==
                    {3'b0,s_data_data[12:0]}) &&
        (({3'b0,s_data_data[12:0]}-s_data_data[31:16]>=256 &&
             incoming_bytes==256) ||
         ({3'b0,s_data_data[12:0]}-s_data_data[31:16]<256 &&
             incoming_bytes=={3'b0,s_data_data[12:0]}-s_data_data[31:16]));

    integer admission_slot;
    reg accept_new, accept_duplicate;
    always @* begin
        admission_slot=incoming_stream*8+(incoming_packet&7);
        accept_new=0;
        accept_duplicate=0;
        if (parse_phase==6 && parse_good) begin
            if (incoming_identity<receive_base[incoming_stream]) begin
                accept_duplicate=1;
            end else if (incoming_identity >= {29'b0,incoming_packet} &&
                incoming_identity-{29'b0,incoming_packet}==
                    receive_base[incoming_stream] &&
                (!active[incoming_stream] ||
                    message_len[incoming_stream]==incoming_len)) begin
                if (active[incoming_stream] &&
                    (incoming_packet<copied[incoming_stream] ||
                     (slot_valid[admission_slot] &&
                        slot_index[admission_slot]==incoming_packet)))
                    accept_duplicate=1;
                else if (!complete[incoming_stream] &&
                    incoming_packet>=copied[incoming_stream] &&
                    {1'b0,incoming_packet}-copied[incoming_stream]<8 &&
                    !slot_valid[admission_slot])
                    accept_new=1;
            end
        end
    end

    reg copying;
    reg [1:0] copy_stream, copy_rr;
    reg [3:0] copy_packet;
    reg [5:0] copy_word;
    reg [8:0] copy_bytes;
    integer copy_choice, copy_slot, copy_scan, cf;
    always @* begin
        copy_choice=-1;
        copy_slot=0;
        cf=0;
        for (copy_scan=0;copy_scan<4;copy_scan=copy_scan+1) begin
            cf=(copy_rr+copy_scan)&3;
            if (copy_choice<0 && active[cf] && !complete[cf] &&
                copied[cf]<message_packets[cf] &&
                slot_valid[cf*8+(copied[cf]&7)] &&
                slot_index[cf*8+(copied[cf]&7)]==copied[cf]) begin
                copy_choice=cf;
                copy_slot=cf*8+(copied[cf]&7);
            end
        end
    end

    reg msg_v,msg_f,msg_l;
    reg [63:0] msg_d;
    reg [7:0] msg_k;
    reg [1:0] msg_s, msg_rr;
    reg [12:0] msg_n;
    integer message_choice, message_scan, mf, message_remaining;
    reg [7:0] selected_keep;
    always @* begin
        message_choice=-1;
        mf=0;
        for (message_scan=0;message_scan<4;message_scan=message_scan+1) begin
            mf=(msg_rr+message_scan)&3;
            if (message_choice<0 && complete[mf]) message_choice=mf;
        end
        message_remaining=0;
        selected_keep=0;
        if (message_choice>=0) begin
            message_remaining=message_len[message_choice]-
                output_word[message_choice]*8;
            selected_keep=byte_keep(message_remaining);
        end
    end

    reg [33:0] ack_fifo [0:31];
    reg [4:0] ack_read, ack_write;
    reg [5:0] ack_count;
    reg ack_sending;
    reg [1:0] ack_stream, ack_phase;
    reg [31:0] ack_identity, ack_crc;
    reg ack_v,ack_f,ack_l;
    reg [63:0] ack_d;
    reg [7:0] ack_k;
    reg [63:0] ack_build;
    wire ack_pop=!ack_sending && ack_count!=0;
    wire ack_request=accept_duplicate ||
        (parse_phase==7 && commit_word+1>=incoming_words);
    wire ack_push=ack_request && (ack_count<32 || ack_pop);
    always @* begin
        ack_build=0;
        case (ack_phase)
            0: begin
                ack_build[31:0]=32'h01014253;
                ack_build[39:32]={6'b0,ack_stream};
            end
            1: ack_build={ack_identity,session};
            2: ack_build=0;
            3: ack_build={32'b0,~ack_crc};
        endcase
    end

    assign s_data_ready=!rst && parse_phase<=5;
    assign m_msg_valid=!rst && msg_v;
    assign m_msg_data=rst ? 64'b0 : msg_d;
    assign m_msg_keep=rst ? 8'b0 : msg_k;
    assign m_msg_first=!rst && msg_f;
    assign m_msg_last=!rst && msg_l;
    assign m_msg_stream=rst ? 2'b0 : msg_s;
    assign m_msg_len=rst ? 13'b0 : msg_n;
    assign m_ack_valid=!rst && ack_v;
    assign m_ack_data=rst ? 64'b0 : ack_d;
    assign m_ack_keep=rst ? 8'b0 : ack_k;
    assign m_ack_first=!rst && ack_f;
    assign m_ack_last=!rst && ack_l;

    integer i, target_slot;
    always @(posedge clk) begin
        if (rst) begin
            session<=session_id;
            active<=0; complete<=0; slot_valid<=0;
            parse_phase<=0; parse_good<=0; h0<=0; h1<=0; h2<=0;
            parse_crc<=32'hffffffff; payload_word<=0; commit_word<=0;
            copying<=0; copy_stream<=0; copy_rr<=0; copy_packet<=0;
            copy_word<=0; copy_bytes<=0;
            msg_v<=0; msg_f<=0; msg_l<=0; msg_d<=0; msg_k<=0;
            msg_s<=0; msg_rr<=0; msg_n<=0;
            ack_read<=0; ack_write<=0; ack_count<=0; ack_sending<=0;
            ack_stream<=0; ack_phase<=0; ack_identity<=0;
            ack_crc<=32'hffffffff; ack_v<=0; ack_f<=0; ack_l<=0;
            ack_d<=0; ack_k<=0;
            for (i=0;i<4;i=i+1) begin
                receive_base[i]<=0; message_len[i]<=0; message_packets[i]<=0;
                copied[i]<=0; output_word[i]<=0;
            end
            for (i=0;i<32;i=i+1) begin slot_index[i]<=0; slot_bytes[i]<=0; end
        end else begin
            if (s_data_valid && s_data_ready) begin
                if (s_data_first) begin
                    h0<=s_data_data;
                    parse_crc<=crc_word(32'hffffffff,s_data_data,8'hff);
                    payload_word<=0;
                    parse_good<=!s_data_last && s_data_keep==8'hff &&
                        s_data_data[31:0]==32'h00014253 &&
                        s_data_data[39:34]==0 && s_data_data[47:42]==0 &&
                        s_data_data[63:48]>=1 && s_data_data[63:48]<=256;
                    if (s_data_last) parse_phase<=0;
                    else if (s_data_data[63:48]>=1 && s_data_data[63:48]<=256)
                        parse_phase<=1;
                    else parse_phase<=5;
                end else begin
                    case (parse_phase)
                        1: begin
                            h1<=s_data_data;
                            parse_crc<=crc_word(parse_crc,s_data_data,8'hff);
                            parse_good<=parse_good && !s_data_last &&
                                s_data_keep==8'hff && s_data_data[31:0]==session &&
                                {1'b0,s_data_data[63:32]}<ID_LIMIT;
                            if (s_data_last) parse_phase<=0;
                            else parse_phase<=2;
                        end
                        2: begin
                            h2<=s_data_data;
                            parse_crc<=crc_word(parse_crc,s_data_data,8'hff);
                            parse_good<=parse_good && !s_data_last &&
                                s_data_keep==8'hff && structural_h2;
                            if (s_data_last) parse_phase<=0;
                            else parse_phase<=3;
                        end
                        3: begin
                            staging[payload_word[4:0]]<=
                                clean_word(s_data_data,payload_keep);
                            parse_crc<=crc_word(parse_crc,s_data_data,payload_keep);
                            parse_good<=parse_good && !s_data_last &&
                                s_data_keep==payload_keep;
                            if (s_data_last) parse_phase<=0;
                            else if (payload_word+1>=payload_expected_words)
                                parse_phase<=4;
                            else payload_word<=payload_word+1'b1;
                        end
                        4: begin
                            parse_good<=parse_good && s_data_last &&
                                s_data_keep==8'h0f && s_data_data[63:32]==0 &&
                                s_data_data[31:0]==~parse_crc;
                            if (s_data_last) parse_phase<=6;
                            else parse_phase<=5;
                        end
                        5: if (s_data_last) begin parse_phase<=0; parse_good<=0; end
                        default: begin parse_phase<=0; parse_good<=0; end
                    endcase
                end
            end
            if (parse_phase==6) begin
                if (accept_new) begin
                    if (!active[incoming_stream]) begin
                        active[incoming_stream]<=1;
                        message_len[incoming_stream]<=incoming_len;
                        message_packets[incoming_stream]<=incoming_packets;
                        copied[incoming_stream]<=0;
                        output_word[incoming_stream]<=0;
                    end
                    commit_word<=0;
                    parse_phase<=7;
                end else begin parse_phase<=0; parse_good<=0; end
            end
            if (parse_phase==7) begin
                packet_mem[incoming_stream*256+(incoming_packet&7)*32+
                    commit_word]<=staging[commit_word];
                if (commit_word+1>=incoming_words) begin
                    slot_valid[admission_slot]<=1;
                    slot_index[admission_slot]<=incoming_packet;
                    slot_bytes[admission_slot]<=incoming_bytes;
                    parse_phase<=0; parse_good<=0;
                end else commit_word<=commit_word+1'b1;
            end

            if (!copying && copy_choice>=0) begin
                copying<=1;
                copy_stream<=copy_choice[1:0];
                copy_packet<=copied[copy_choice][3:0];
                copy_bytes<=slot_bytes[copy_slot];
                copy_word<=0;
                copy_rr<=copy_choice[1:0]+1'b1;
            end else if (copying) begin
                message_mem[copy_stream*512+copy_packet*32+copy_word]<=
                    packet_mem[copy_stream*256+(copy_packet&7)*32+copy_word];
                if ((copy_word+1)*8>=copy_bytes) begin
                    copying<=0;
                    slot_valid[copy_stream*8+(copy_packet&7)]<=0;
                    copied[copy_stream]<=copied[copy_stream]+1'b1;
                    if (copied[copy_stream]+1==message_packets[copy_stream])
                        complete[copy_stream]<=1;
                end else copy_word<=copy_word+1'b1;
            end

            if (!msg_v && message_choice>=0) begin
                msg_v<=1;
                msg_d<=clean_word(message_mem[message_choice*512+
                    output_word[message_choice]],selected_keep);
                msg_k<=selected_keep;
                msg_s<=message_choice[1:0];
                msg_n<=message_len[message_choice];
                msg_f<=(output_word[message_choice]==0);
                msg_l<=(message_remaining<=8);
            end else if (msg_v && m_msg_ready) begin
                msg_v<=0; msg_d<=0; msg_k<=0; msg_f<=0; msg_l<=0; msg_n<=0;
                msg_rr<=msg_s+1'b1;
                msg_s<=0;
                if (msg_l) begin
                    active[msg_s]<=0;
                    complete[msg_s]<=0;
                    receive_base[msg_s]<=receive_base[msg_s]+
                        {28'b0,message_packets[msg_s]};
                    copied[msg_s]<=0;
                    output_word[msg_s]<=0;
                end else output_word[msg_s]<=output_word[msg_s]+1'b1;
            end

            if (ack_push) begin
                ack_fifo[ack_write]<={incoming_stream,incoming_id};
                ack_write<=ack_write+1'b1;
            end
            case ({ack_push,ack_pop})
                2'b10: ack_count<=ack_count+1'b1;
                2'b01: ack_count<=ack_count-1'b1;
                default: begin end
            endcase
            if (ack_pop) begin
                ack_stream<=ack_fifo[ack_read][33:32];
                ack_identity<=ack_fifo[ack_read][31:0];
                ack_read<=ack_read+1'b1;
                ack_sending<=1;
                ack_phase<=0;
                ack_crc<=32'hffffffff;
            end
            if (ack_sending && !ack_v) begin
                ack_v<=1;
                ack_d<=ack_build;
                if (ack_phase==3) ack_k<=8'h0f;
                else ack_k<=8'hff;
                ack_f<=(ack_phase==0);
                ack_l<=(ack_phase==3);
            end else if (ack_v && m_ack_ready) begin
                ack_v<=0; ack_d<=0; ack_k<=0; ack_f<=0; ack_l<=0;
                if (ack_phase==3) ack_sending<=0;
                else begin
                    ack_crc<=crc_word(ack_crc,ack_d,ack_k);
                    ack_phase<=ack_phase+1'b1;
                end
            end
        end
    end
endmodule

module bridge;
    parameter integer MODE=2;
    parameter integer TIMEOUT_CYCLES=4096;
    parameter integer MAX_RETRIES=4;
    parameter integer GENERATION_BITS=24;
    reg clk=0;
    reg rst=1;
    reg [31:0] session_id=0;
    reg [255:0] drive[0:1];
    wire [255:0] observe[0:1];
    integer fd, n, cycle, i;
    reg [1023:0] input_path;
    generate for (genvar g=0;g<2;g=g+1) begin: node
        wire iv,ifi,ila,mr,sr,lr,lv,lf,ll;
        wire [63:0] id,ld;
        wire [7:0] ik,lk;
        wire [1:0] istr;
        wire [12:0] ilen;
        assign {iv,id,ik,ifi,ila,istr,ilen,mr,sr,lr,lv,ld,lk,lf,ll}=drive[g][168:0];
        wire ir,mv,mf,ml,sv,tv,tf,tl,rr;
        wire [63:0] md,td;
        wire [7:0] mk,tk;
        wire [1:0] ms,ss,sc;
        wire [12:0] mn;
        wire [3:0] fail,exhaust;
        if (MODE==0) begin: tx
            sable_tx #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_RETRIES(MAX_RETRIES),
                       .GENERATION_BITS(GENERATION_BITS)) dut (
                .clk(clk),.rst(rst),.session_id(session_id),
                .s_msg_valid(iv),.s_msg_ready(ir),.s_msg_data(id),.s_msg_keep(ik),
                .s_msg_first(ifi),.s_msg_last(ila),.s_msg_stream(istr),.s_msg_len(ilen),
                .m_status_valid(sv),.m_status_ready(sr),.m_status_stream(ss),.m_status_code(sc),
                .tx_failed(fail),.session_exhausted(exhaust),
                .m_data_valid(tv),.m_data_ready(lr),.m_data_data(td),.m_data_keep(tk),
                .m_data_first(tf),.m_data_last(tl),.s_ack_valid(lv),.s_ack_ready(rr),
                .s_ack_data(ld),.s_ack_keep(lk),.s_ack_first(lf),.s_ack_last(ll));
            assign {mv,md,mk,mf,ml,ms,mn}=0;
        end else if (MODE==1) begin: rx
            sable_rx #(.GENERATION_BITS(GENERATION_BITS)) dut (
                .clk(clk),.rst(rst),.session_id(session_id),
                .s_data_valid(lv),.s_data_ready(rr),.s_data_data(ld),.s_data_keep(lk),
                .s_data_first(lf),.s_data_last(ll),
                .m_msg_valid(mv),.m_msg_ready(mr),.m_msg_data(md),.m_msg_keep(mk),
                .m_msg_first(mf),.m_msg_last(ml),.m_msg_stream(ms),.m_msg_len(mn),
                .m_ack_valid(tv),.m_ack_ready(lr),.m_ack_data(td),.m_ack_keep(tk),
                .m_ack_first(tf),.m_ack_last(tl));
            assign {ir,sv,ss,sc,fail,exhaust}=0;
        end else begin: endpoint
            sable_endpoint #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_RETRIES(MAX_RETRIES),
                             .GENERATION_BITS(GENERATION_BITS)) dut (
                .clk(clk),.rst(rst),.session_id(session_id),
                .s_msg_valid(iv),.s_msg_ready(ir),.s_msg_data(id),.s_msg_keep(ik),
                .s_msg_first(ifi),.s_msg_last(ila),.s_msg_stream(istr),.s_msg_len(ilen),
                .m_msg_valid(mv),.m_msg_ready(mr),.m_msg_data(md),.m_msg_keep(mk),
                .m_msg_first(mf),.m_msg_last(ml),.m_msg_stream(ms),.m_msg_len(mn),
                .m_status_valid(sv),.m_status_ready(sr),.m_status_stream(ss),.m_status_code(sc),
                .tx_failed(fail),.session_exhausted(exhaust),
                .link_tx_valid(tv),.link_tx_ready(lr),.link_tx_data(td),.link_tx_keep(tk),
                .link_tx_first(tf),.link_tx_last(tl),.link_rx_valid(lv),.link_rx_ready(rr),
                .link_rx_data(ld),.link_rx_keep(lk),.link_rx_first(lf),.link_rx_last(ll));
        end
        assign observe[g]={ir,mv,md,mk,mf,ml,ms,mn,sv,ss,sc,fail,exhaust,tv,td,tk,tf,tl,rr};
        always @(posedge clk or negedge clk) begin
            if ((^observe[g])===1'bx) $fatal(1,"PUBLIC_XZ node=%0d cycle=%0d",g,cycle);
            if (rst && observe[g]!==256'b0) $fatal(1,"RESET_OUTPUT node=%0d",g);
        end
    end endgenerate
    initial begin
        cycle=0;
        drive[0]=0; drive[1]=0;
        // Reset starts asserted at time zero; observe after combinational settling.
        #1;
        if (observe[0]!==0 || observe[1]!==0) $fatal(1,"TIME_ZERO_RESET");
        if (!$value$plusargs("INPUT=%s",input_path)) input_path="/dev/stdin";
        fd=$fopen(input_path,"r");
        if (!fd) $fatal(1,"INPUT_OPEN");
        forever begin
            n=$fscanf(fd,"%h %h %h %h",rst,session_id,drive[0],drive[1]);
            if (n!=4) begin
                if ((n==-1 || n==0) && $feof(fd)) $finish;
                $fatal(1,"MALFORMED_VECTOR count=%0d",n);
            end
            #1;
            $display("OBS %064h %064h",observe[0],observe[1]);
            $fflush();
            #1 clk=1;
            #1 clk=0;
            cycle=cycle+1;
        end
    end
endmodule

module sable_endpoint #(
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
    output wire m_msg_valid,
    input wire m_msg_ready,
    output wire [63:0] m_msg_data,
    output wire [7:0] m_msg_keep,
    output wire m_msg_first, m_msg_last,
    output wire [1:0] m_msg_stream,
    output wire [12:0] m_msg_len,
    output wire m_status_valid,
    input wire m_status_ready,
    output wire [1:0] m_status_stream, m_status_code,
    output wire [3:0] tx_failed, session_exhausted,
    output wire link_tx_valid,
    input wire link_tx_ready,
    output wire [63:0] link_tx_data,
    output wire [7:0] link_tx_keep,
    output wire link_tx_first, link_tx_last,
    input wire link_rx_valid,
    output wire link_rx_ready,
    input wire [63:0] link_rx_data,
    input wire [7:0] link_rx_keep,
    input wire link_rx_first, link_rx_last
);
    wire data_v,data_r,data_f,data_l;
    wire [63:0] data_d;
    wire [7:0] data_k;
    wire ack_v,ack_r,ack_f,ack_l;
    wire [63:0] ack_d;
    wire [7:0] ack_k;
    wire rx_data_r,rx_ack_r;

    reg input_v,input_f,input_l,input_ack;
    reg [63:0] input_d;
    reg [7:0] input_k;
    reg input_locked,input_route;
    wire input_ready=input_ack ? rx_ack_r : rx_data_r;

    sable_tx #(
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES), .MAX_RETRIES(MAX_RETRIES),
        .GENERATION_BITS(GENERATION_BITS)
    ) u_tx (
        .clk(clk), .rst(rst), .session_id(session_id),
        .s_msg_valid(s_msg_valid), .s_msg_ready(s_msg_ready),
        .s_msg_data(s_msg_data), .s_msg_keep(s_msg_keep),
        .s_msg_first(s_msg_first), .s_msg_last(s_msg_last),
        .s_msg_stream(s_msg_stream), .s_msg_len(s_msg_len),
        .m_status_valid(m_status_valid), .m_status_ready(m_status_ready),
        .m_status_stream(m_status_stream), .m_status_code(m_status_code),
        .tx_failed(tx_failed), .session_exhausted(session_exhausted),
        .m_data_valid(data_v), .m_data_ready(data_r),
        .m_data_data(data_d), .m_data_keep(data_k),
        .m_data_first(data_f), .m_data_last(data_l),
        .s_ack_valid(input_v && input_ack && !rst),
        .s_ack_ready(rx_ack_r), .s_ack_data(input_d), .s_ack_keep(input_k),
        .s_ack_first(input_f), .s_ack_last(input_l)
    );
    sable_rx #(.GENERATION_BITS(GENERATION_BITS)) u_rx (
        .clk(clk), .rst(rst), .session_id(session_id),
        .s_data_valid(input_v && !input_ack && !rst),
        .s_data_ready(rx_data_r), .s_data_data(input_d), .s_data_keep(input_k),
        .s_data_first(input_f), .s_data_last(input_l),
        .m_msg_valid(m_msg_valid), .m_msg_ready(m_msg_ready),
        .m_msg_data(m_msg_data), .m_msg_keep(m_msg_keep),
        .m_msg_first(m_msg_first), .m_msg_last(m_msg_last),
        .m_msg_stream(m_msg_stream), .m_msg_len(m_msg_len),
        .m_ack_valid(ack_v), .m_ack_ready(ack_r),
        .m_ack_data(ack_d), .m_ack_keep(ack_k),
        .m_ack_first(ack_f), .m_ack_last(ack_l)
    );

    reg output_v,output_f,output_l;
    reg [63:0] output_d;
    reg [7:0] output_k;
    reg owner_valid,owner_ack,prefer_ack;
    wire select_ack=owner_valid ? owner_ack :
        (ack_v && (!data_v || prefer_ack));
    wire selected_valid=select_ack ? ack_v : data_v;
    assign data_r=!rst && !output_v && !select_ack;
    assign ack_r=!rst && !output_v && select_ack;
    assign link_tx_valid=!rst && output_v;
    assign link_tx_data=rst ? 64'b0 : output_d;
    assign link_tx_keep=rst ? 8'b0 : output_k;
    assign link_tx_first=!rst && output_f;
    assign link_tx_last=!rst && output_l;
    assign link_rx_ready=!rst && !input_v;

    always @(posedge clk) begin
        if (rst) begin
            input_v<=0; input_f<=0; input_l<=0; input_ack<=0;
            input_d<=0; input_k<=0; input_locked<=0; input_route<=0;
            output_v<=0; output_f<=0; output_l<=0; output_d<=0; output_k<=0;
            owner_valid<=0; owner_ack<=0; prefer_ack<=1;
        end else begin
            if (input_v && input_ready) begin
                input_v<=0; input_d<=0; input_k<=0; input_f<=0; input_l<=0;
                input_ack<=0;
            end
            if (link_rx_valid && link_rx_ready) begin
                if (link_rx_first || input_locked) begin
                    input_v<=1;
                    input_d<=link_rx_data;
                    input_k<=link_rx_keep;
                    input_f<=link_rx_first;
                    input_l<=link_rx_last;
                    if (link_rx_first) begin
                        input_ack<=(link_rx_data[31:24]==8'h01);
                        input_route<=(link_rx_data[31:24]==8'h01);
                    end else input_ack<=input_route;
                    input_locked<=!link_rx_last;
                end
            end
            if (!output_v && selected_valid) begin
                output_v<=1;
                owner_valid<=1;
                owner_ack<=select_ack;
                if (select_ack) begin
                    output_d<=ack_d; output_k<=ack_k;
                    output_f<=ack_f; output_l<=ack_l;
                end else begin
                    output_d<=data_d; output_k<=data_k;
                    output_f<=data_f; output_l<=data_l;
                end
            end else if (output_v && link_tx_ready) begin
                output_v<=0; output_d<=0; output_k<=0; output_f<=0; output_l<=0;
                if (output_l) begin
                    owner_valid<=0;
                    prefer_ack<=!owner_ack;
                end
            end
        end
    end
endmodule

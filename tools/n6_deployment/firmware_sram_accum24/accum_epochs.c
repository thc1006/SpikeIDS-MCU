/* SM05 derived epoch19: exact-width candidate, NOT vendor-generated unmodified output. */
static void SM05_Start_19(const void *epoch_block)
{
  LL_ATON_LIB_UNUSED(epoch_block);

  /* Unit= 10 [CONV_ACC_V2 0] */
  /* kind=Conv node=Gemm_27_conv_10 */
  static const LL_Convacc_InitTypeDef Gemm_27_conv_10_init19 = {
    .simd = 1,
    .fsub = 0,
    .vshift = 0,
    .accumulate = 0,
    .kfilt_tot = 32,
    .kfilt_first = 0,
    .kfilt_last = 15,
    .rounding_f = 0,
    .saturation_f = 0,
    .round_mode_f = 0,
    .f_unsigned = 1,
    .k_unsigned = 0,
    .deepmode = 1,
    .dss2mode = 0,
    .kseten = 3,
    .zfbias = 0,
    .inbytes_f = 3,
    .shift_f = 0,
    .shift_a = 6,
    .rounding_o = 1,
    .saturation_o = 1,
    .round_mode_o = 1,
    .relu_mode_o = 0,
    .outbytes_o = 3,
    .shift_o = 0,
    .raw_o = 1,
    .fWidth = 1,
    .fHeight = 1,
    .kernelWidth = 1,
    .kernelHeight = 1,
    .nKernels = 16,
    .batchDepth = 128,
    .hstride = 1,
    .vstride = 1,
    .left_padding = 0,
    .right_padding = 0,
    .top_padding = 0,
    .bot_padding = 0,
    .left_crop = 0,
    .right_crop = 0,
    .top_crop = 0,
    .bot_crop = 0,
  };

  /* Unit=CONV_ACC_V2 */
  LL_Convacc_Init(0, &Gemm_27_conv_10_init19);


  /* Unit= 11 [CONV_ACC_V2 1] */
  /* kind=Conv node=Gemm_27_conv_10_ca_pipe_1 */
  static const LL_Convacc_InitTypeDef Gemm_27_conv_10_ca_pipe_1_init19 = {
    .simd = 1,
    .fsub = 0,
    .vshift = 0,
    .accumulate = 1,
    .accumulate_first = 1,
    .kfilt_tot = 32,
    .kfilt_first = 16,
    .kfilt_last = 31,
    .rounding_f = 0,
    .saturation_f = 0,
    .round_mode_f = 0,
    .f_unsigned = 1,
    .k_unsigned = 0,
    .deepmode = 1,
    .dss2mode = 0,
    .kseten = 3,
    .zfbias = 0,
    .inbytes_f = 3,
    .shift_f = 0,
    .shift_a = 0,
    .rounding_o = 0,
    .saturation_o = 1,
    .round_mode_o = 1,
    .relu_mode_o = 0,
    .outbytes_o = 3,
    .shift_o = 0,
    .raw_o = 0,
    .fWidth = 1,
    .fHeight = 1,
    .kernelWidth = 1,
    .kernelHeight = 1,
    .nKernels = 16,
    .batchDepth = 128,
    .hstride = 1,
    .vstride = 1,
    .left_padding = 0,
    .right_padding = 0,
    .top_padding = 0,
    .bot_padding = 0,
    .left_crop = 0,
    .right_crop = 0,
    .top_crop = 0,
    .bot_crop = 0,
  };

  /* Unit=CONV_ACC_V2 */
  LL_Convacc_Init(1, &Gemm_27_conv_10_ca_pipe_1_init19);


  /* Unit= 21 [ARITH_ACC_V2 3] */
  /* kind=Add node=Gemm_27_conv_10_off_bias_39 */



  /* Dma inputs units to cycle: */
  /* Unit= 3 [STREAM_ENG_V2 3] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_27_conv_10 input ports=0 range=0[0,256] */

  static const LL_Streng_TensorInitTypeDef Gemm_27_conv_10_dma_init_in_0_19 = {
    /* 1x1x128(8 bits) */
    .dir = 0,
    .raw = 1,
    .raw_out = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 1,
    .addr_base = {(unsigned char *)(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_27_conv_10_zero_off_out_34 */
    .offset_start = 0,
    .offset_end = 129,
    .offset_limit = 320,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 256,
    .frame_loop_cnt = 16,
    .frame_tot_cnt = 16,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(3, &Gemm_27_conv_10_dma_init_in_0_19, 1);

  /* Unit= 7 [STREAM_ENG_V2 7] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_27_conv_10 input ports=1 range=1[0,65568] */

  static const LL_Streng_TensorInitTypeDef Gemm_27_conv_10_dma_init_in_1_19 = {
    /* 256x1x1x256(8 bits) */
    .dir = 0,
    .raw = 1,
    .continuous = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 0,
    .addr_base = {(unsigned char *)(0x34200000UL) /* Equivalent hex address = 0x34200000UL */}, /* Gemm_27_weights_transposed_9 */
    .offset_start = 0,
    .offset_end = 65568,
    .offset_limit = 65632,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 0,
    .frame_loop_cnt = 0,
    .frame_tot_cnt = 1,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(7, &Gemm_27_conv_10_dma_init_in_1_19, 1);

  /* Unit= 0 [STREAM_ENG_V2 0] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_27_conv_10_ca_pipe_1 input ports=0 range=0[0,256] */

  static const LL_Streng_TensorInitTypeDef Gemm_27_conv_10_ca_pipe_1_dma_init_in_0_19 = {
    /* 1x1x128(8 bits) */
    .dir = 0,
    .raw = 1,
    .raw_out = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 1,
    .addr_base = {(unsigned char *)ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_27_conv_10_zero_off_out_34_copy_in_5 ca pipe offset=1 */
    .offset_start = 128,
    .offset_end = 257,
    .offset_limit = 320,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 256,
    .frame_loop_cnt = 16,
    .frame_tot_cnt = 16,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(0, &Gemm_27_conv_10_ca_pipe_1_dma_init_in_0_19, 1);


  /* Dma input bandwidth from memory pools: */
  /* activations_sram -> 4096 */
  /* weights_sram -> 65536 */

  /* Dma output units from cycle: */
  /* Unit= 8 [STREAM_ENG_V2 8] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_27_conv_10_off_bias_39 output ports=0 range=0[1024,1280] */

  static const LL_Streng_TensorInitTypeDef Gemm_27_conv_10_off_bias_39_dma_init_out_0_19 = {
    /* to memory with batch=16 */
    .dir = 1,
    .raw = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 0,
    .addr_base = {(unsigned char *)(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_27_conv_10_off_bias_out_40 */
    .offset_start = 8192,
    .offset_end = 8240,
    .offset_limit = 9024,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 48,
    .line_offset = 0,
    .loop_offset = 0,
    .frame_loop_cnt = 0,
    .frame_tot_cnt = 16,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(8, &Gemm_27_conv_10_off_bias_39_dma_init_out_0_19, 1);


  /* Dma output bandwidth to memory pools: */
  /* activations_sram <- 256 */

  static const LL_Switch_InitTypeDef switch_init_in_19[] = {
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 3, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10 IN: in unit=CONV_ACC_V2 0 in port=0 out unit=STREAM_ENG_V2 3 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 7, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10 IN: in unit=CONV_ACC_V2 0 in port=1 out unit=STREAM_ENG_V2 7 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 1, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_ca_pipe_1 IN: in unit=CONV_ACC_V2 1 in port=0 out unit=STREAM_ENG_V2 0 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 1, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 7, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_ca_pipe_1 IN: in unit=CONV_ACC_V2 1 in port=1 out unit=STREAM_ENG_V2 7 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 1, 2), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_ca_pipe_1 IN: in unit=CONV_ACC_V2 1 in port=2 out unit=CONV_ACC_V2 0 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, STRENG, 8, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 1, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_off_bias_39 OUT: in unit=STREAM_ENG_V2 8 in port=0 out unit=ARITH_ACC_V2 3 out port=0 */
  };


  /* epoch=19 */
  LL_Switch_Init(switch_init_in_19, 6);

  /* *** MCU cache invalidate (only) operation (HW, whole range) *** */
  /*     memory pool: 0 */
  /*     start: ((uintptr_t)(ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 1024))) */
  /*     end:   ((uintptr_t)(ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 1280))) */
  LL_ATON_Cache_MCU_Invalidate_Range((uintptr_t)0x34242000UL, 768);

  static const LL_ATON_EnableUnits_InitTypeDef Enable_epoch_19_all_units[] = {
    { {STRENG, 8} }, /* STREAM_ENG_V2 */
    { {CONVACC, 0} }, /* CONV_ACC_V2 */
    { {CONVACC, 1} }, /* CONV_ACC_V2 */
    { {STRENG, 0} }, /* STREAM_ENG_V2 */
    { {STRENG, 3} }, /* STREAM_ENG_V2 */
    { {STRENG, 7} }, /* STREAM_ENG_V2 */
  };


  LL_ATON_EnableUnits_Init(Enable_epoch_19_all_units, 6);


}

/* SM05 derived epoch19: exact-width candidate, NOT vendor-generated unmodified output. */
static void SM05_End_19(const void *epoch_block)
{
  LL_ATON_LIB_UNUSED(epoch_block);

  static const LL_Switch_DeinitTypeDef switch_deinit_in_19[] = {
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 3, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10 IN: in unit=CONV_ACC_V2 0 in port=0 out unit=STREAM_ENG_V2 3 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 7, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10 IN: in unit=CONV_ACC_V2 0 in port=1 out unit=STREAM_ENG_V2 7 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 1, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_ca_pipe_1 IN: in unit=CONV_ACC_V2 1 in port=0 out unit=STREAM_ENG_V2 0 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 1, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 7, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_ca_pipe_1 IN: in unit=CONV_ACC_V2 1 in port=1 out unit=STREAM_ENG_V2 7 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 1, 2), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_ca_pipe_1 IN: in unit=CONV_ACC_V2 1 in port=2 out unit=CONV_ACC_V2 0 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, STRENG, 8, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 1, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_27_conv_10_off_bias_39 OUT: in unit=STREAM_ENG_V2 8 in port=0 out unit=ARITH_ACC_V2 3 out port=0 */
  };


  /* epoch=19 */
  LL_Switch_Deinit(switch_deinit_in_19, 6);

  static const LL_ATON_DisableUnits_InitTypeDef Disable_epoch_19_all_units[] = {
    { {STRENG, 8} }, /* STREAM_ENG_V2 */
    { {CONVACC, 0} }, /* CONV_ACC_V2 */
    { {CONVACC, 1} }, /* CONV_ACC_V2 */
    { {STRENG, 0} }, /* STREAM_ENG_V2 */
    { {STRENG, 3} }, /* STREAM_ENG_V2 */
    { {STRENG, 7} }, /* STREAM_ENG_V2 */
  };


  LL_ATON_DisableUnits_Init(Disable_epoch_19_all_units, 6);


}

/* SM05 derived epoch31: exact-width candidate, NOT vendor-generated unmodified output. */
static void SM05_Start_31(const void *epoch_block)
{
  LL_ATON_LIB_UNUSED(epoch_block);

  /* Unit= 12 [CONV_ACC_V2 2] */
  /* kind=Conv node=Gemm_39_conv_16 */
  static const LL_Convacc_InitTypeDef Gemm_39_conv_16_init31 = {
    .simd = 1,
    .fsub = 0,
    .vshift = 0,
    .accumulate = 0,
    .kfilt_tot = 32,
    .kfilt_first = 0,
    .kfilt_last = 15,
    .rounding_f = 0,
    .saturation_f = 0,
    .round_mode_f = 0,
    .f_unsigned = 1,
    .k_unsigned = 0,
    .deepmode = 1,
    .dss2mode = 0,
    .kseten = 3,
    .zfbias = 0,
    .inbytes_f = 3,
    .shift_f = 0,
    .shift_a = 5,
    .rounding_o = 1,
    .saturation_o = 1,
    .round_mode_o = 1,
    .relu_mode_o = 0,
    .outbytes_o = 3,
    .shift_o = 0,
    .raw_o = 1,
    .fWidth = 1,
    .fHeight = 1,
    .kernelWidth = 1,
    .kernelHeight = 1,
    .nKernels = 16,
    .batchDepth = 128,
    .hstride = 1,
    .vstride = 1,
    .left_padding = 0,
    .right_padding = 0,
    .top_padding = 0,
    .bot_padding = 0,
    .left_crop = 0,
    .right_crop = 0,
    .top_crop = 0,
    .bot_crop = 0,
  };

  /* Unit=CONV_ACC_V2 */
  LL_Convacc_Init(2, &Gemm_39_conv_16_init31);


  /* Unit= 13 [CONV_ACC_V2 3] */
  /* kind=Conv node=Gemm_39_conv_16_ca_pipe_1 */
  static const LL_Convacc_InitTypeDef Gemm_39_conv_16_ca_pipe_1_init31 = {
    .simd = 1,
    .fsub = 0,
    .vshift = 0,
    .accumulate = 1,
    .accumulate_first = 1,
    .kfilt_tot = 32,
    .kfilt_first = 16,
    .kfilt_last = 31,
    .rounding_f = 0,
    .saturation_f = 0,
    .round_mode_f = 0,
    .f_unsigned = 1,
    .k_unsigned = 0,
    .deepmode = 1,
    .dss2mode = 0,
    .kseten = 3,
    .zfbias = 0,
    .inbytes_f = 3,
    .shift_f = 0,
    .shift_a = 0,
    .rounding_o = 0,
    .saturation_o = 1,
    .round_mode_o = 1,
    .relu_mode_o = 0,
    .outbytes_o = 3,
    .shift_o = 0,
    .raw_o = 0,
    .fWidth = 1,
    .fHeight = 1,
    .kernelWidth = 1,
    .kernelHeight = 1,
    .nKernels = 16,
    .batchDepth = 128,
    .hstride = 1,
    .vstride = 1,
    .left_padding = 0,
    .right_padding = 0,
    .top_padding = 0,
    .bot_padding = 0,
    .left_crop = 0,
    .right_crop = 0,
    .top_crop = 0,
    .bot_crop = 0,
  };

  /* Unit=CONV_ACC_V2 */
  LL_Convacc_Init(3, &Gemm_39_conv_16_ca_pipe_1_init31);


  /* Unit= 19 [ARITH_ACC_V2 1] */
  /* kind=Add node=Gemm_39_conv_16_off_bias_48 */



  /* Dma inputs units to cycle: */
  /* Unit= 3 [STREAM_ENG_V2 3] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_39_conv_16 input ports=0 range=0[0,256] */

  static const LL_Streng_TensorInitTypeDef Gemm_39_conv_16_dma_init_in_0_31 = {
    /* 1x1x128(8 bits) */
    .dir = 0,
    .raw = 1,
    .raw_out = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 1,
    .addr_base = {(unsigned char *)(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_39_conv_16_zero_off_out_43 */
    .offset_start = 0,
    .offset_end = 129,
    .offset_limit = 320,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 256,
    .frame_loop_cnt = 8,
    .frame_tot_cnt = 8,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(3, &Gemm_39_conv_16_dma_init_in_0_31, 1);

  /* Unit= 6 [STREAM_ENG_V2 6] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_39_conv_16 input ports=1 range=1[107552,140336] */

  static const LL_Streng_TensorInitTypeDef Gemm_39_conv_16_dma_init_in_1_31 = {
    /* 128x1x1x256(8 bits) */
    .dir = 0,
    .raw = 1,
    .continuous = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 0,
    .addr_base = {(unsigned char *)(0x34200000UL) /* Equivalent hex address = 0x34200000UL */}, /* Gemm_39_weights_transposed_15 */
    .offset_start = 107552,
    .offset_end = 140336,
    .offset_limit = 140400,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 0,
    .frame_loop_cnt = 0,
    .frame_tot_cnt = 1,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(6, &Gemm_39_conv_16_dma_init_in_1_31, 1);

  /* Unit= 1 [STREAM_ENG_V2 1] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_39_conv_16_ca_pipe_1 input ports=0 range=0[0,256] */

  static const LL_Streng_TensorInitTypeDef Gemm_39_conv_16_ca_pipe_1_dma_init_in_0_31 = {
    /* 1x1x128(8 bits) */
    .dir = 0,
    .raw = 1,
    .raw_out = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 1,
    .addr_base = {(unsigned char *)ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_39_conv_16_zero_off_out_43_copy_in_6 ca pipe offset=1 */
    .offset_start = 128,
    .offset_end = 257,
    .offset_limit = 320,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 256,
    .frame_loop_cnt = 8,
    .frame_tot_cnt = 8,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(1, &Gemm_39_conv_16_ca_pipe_1_dma_init_in_0_31, 1);


  /* Dma input bandwidth from memory pools: */
  /* activations_sram -> 2048 */
  /* weights_sram -> 32768 */

  /* Dma output units from cycle: */
  /* Unit= 5 [STREAM_ENG_V2 5] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_39_conv_16_off_bias_48 output ports=0 range=0[512,640] */

  static const LL_Streng_TensorInitTypeDef Gemm_39_conv_16_off_bias_48_dma_init_out_0_31 = {
    /* to memory with batch=16 */
    .dir = 1,
    .raw = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 0,
    .addr_base = {(unsigned char *)(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_39_conv_16_off_bias_out_49 */
    .offset_start = 8192,
    .offset_end = 8240,
    .offset_limit = 8640,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 48,
    .line_offset = 0,
    .loop_offset = 0,
    .frame_loop_cnt = 0,
    .frame_tot_cnt = 8,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(5, &Gemm_39_conv_16_off_bias_48_dma_init_out_0_31, 1);


  /* Dma output bandwidth to memory pools: */
  /* activations_sram <- 128 */

  static const LL_Switch_InitTypeDef switch_init_in_31[] = {
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 2, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 3, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16 IN: in unit=CONV_ACC_V2 2 in port=0 out unit=STREAM_ENG_V2 3 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 2, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 6, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16 IN: in unit=CONV_ACC_V2 2 in port=1 out unit=STREAM_ENG_V2 6 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 3, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 1, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_ca_pipe_1 IN: in unit=CONV_ACC_V2 3 in port=0 out unit=STREAM_ENG_V2 1 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 3, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 6, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_ca_pipe_1 IN: in unit=CONV_ACC_V2 3 in port=1 out unit=STREAM_ENG_V2 6 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 3, 2), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 2, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_ca_pipe_1 IN: in unit=CONV_ACC_V2 3 in port=2 out unit=CONV_ACC_V2 2 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, STRENG, 5, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 1, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_off_bias_48 OUT: in unit=STREAM_ENG_V2 5 in port=0 out unit=ARITH_ACC_V2 1 out port=0 */
  };


  /* epoch=31 */
  LL_Switch_Init(switch_init_in_31, 6);

  /* *** MCU cache invalidate (only) operation (HW, whole range) *** */
  /*     memory pool: 0 */
  /*     start: ((uintptr_t)(ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 512))) */
  /*     end:   ((uintptr_t)(ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 640))) */
  LL_ATON_Cache_MCU_Invalidate_Range((uintptr_t)0x34242000UL, 384);

  static const LL_ATON_EnableUnits_InitTypeDef Enable_epoch_31_all_units[] = {
    { {STRENG, 5} }, /* STREAM_ENG_V2 */
    { {CONVACC, 2} }, /* CONV_ACC_V2 */
    { {CONVACC, 3} }, /* CONV_ACC_V2 */
    { {STRENG, 1} }, /* STREAM_ENG_V2 */
    { {STRENG, 3} }, /* STREAM_ENG_V2 */
    { {STRENG, 6} }, /* STREAM_ENG_V2 */
  };


  LL_ATON_EnableUnits_Init(Enable_epoch_31_all_units, 6);


}

/* SM05 derived epoch31: exact-width candidate, NOT vendor-generated unmodified output. */
static void SM05_End_31(const void *epoch_block)
{
  LL_ATON_LIB_UNUSED(epoch_block);

  static const LL_Switch_DeinitTypeDef switch_deinit_in_31[] = {
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 2, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 3, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16 IN: in unit=CONV_ACC_V2 2 in port=0 out unit=STREAM_ENG_V2 3 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 2, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 6, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16 IN: in unit=CONV_ACC_V2 2 in port=1 out unit=STREAM_ENG_V2 6 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 3, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 1, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_ca_pipe_1 IN: in unit=CONV_ACC_V2 3 in port=0 out unit=STREAM_ENG_V2 1 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 3, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 6, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_ca_pipe_1 IN: in unit=CONV_ACC_V2 3 in port=1 out unit=STREAM_ENG_V2 6 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 3, 2), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 2, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_ca_pipe_1 IN: in unit=CONV_ACC_V2 3 in port=2 out unit=CONV_ACC_V2 2 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, STRENG, 5, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 1, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_39_conv_16_off_bias_48 OUT: in unit=STREAM_ENG_V2 5 in port=0 out unit=ARITH_ACC_V2 1 out port=0 */
  };


  /* epoch=31 */
  LL_Switch_Deinit(switch_deinit_in_31, 6);

  static const LL_ATON_DisableUnits_InitTypeDef Disable_epoch_31_all_units[] = {
    { {STRENG, 5} }, /* STREAM_ENG_V2 */
    { {CONVACC, 2} }, /* CONV_ACC_V2 */
    { {CONVACC, 3} }, /* CONV_ACC_V2 */
    { {STRENG, 1} }, /* STREAM_ENG_V2 */
    { {STRENG, 3} }, /* STREAM_ENG_V2 */
    { {STRENG, 6} }, /* STREAM_ENG_V2 */
  };


  LL_ATON_DisableUnits_Init(Disable_epoch_31_all_units, 6);


}

/* SM05 derived epoch43: exact-width candidate, NOT vendor-generated unmodified output. */
static void SM05_Start_43(const void *epoch_block)
{
  LL_ATON_LIB_UNUSED(epoch_block);

  /* Unit= 10 [CONV_ACC_V2 0] */
  /* kind=Conv node=Gemm_51_conv_22 */
  static const LL_Convacc_InitTypeDef Gemm_51_conv_22_init43 = {
    .simd = 1,
    .fsub = 0,
    .vshift = 0,
    .accumulate = 0,
    .rounding_f = 0,
    .saturation_f = 0,
    .round_mode_f = 0,
    .f_unsigned = 1,
    .k_unsigned = 0,
    .deepmode = 1,
    .dss2mode = 0,
    .kseten = 3,
    .zfbias = 0,
    .inbytes_f = 3,
    .shift_f = 0,
    .shift_a = 5,
    .rounding_o = 0,
    .saturation_o = 1,
    .round_mode_o = 1,
    .relu_mode_o = 0,
    .outbytes_o = 3,
    .shift_o = 0,
    .raw_o = 0,
    .fWidth = 1,
    .fHeight = 1,
    .kernelWidth = 1,
    .kernelHeight = 1,
    .nKernels = 5,
    .batchDepth = 128,
    .hstride = 1,
    .vstride = 1,
    .left_padding = 0,
    .right_padding = 0,
    .top_padding = 0,
    .bot_padding = 0,
    .left_crop = 0,
    .right_crop = 0,
    .top_crop = 0,
    .bot_crop = 0,
  };

  /* Unit=CONV_ACC_V2 */
  LL_Convacc_Init(0, &Gemm_51_conv_22_init43);


  /* Unit= 21 [ARITH_ACC_V2 3] */
  /* kind=Add node=Gemm_51_conv_22_off_bias_57 */



  /* Dma inputs units to cycle: */
  /* Unit= 9 [STREAM_ENG_V2 9] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_51_conv_22 input ports=0 range=0[0,128] */

  static const LL_Streng_TensorInitTypeDef Gemm_51_conv_22_dma_init_in_0_43 = {
    /* 1x1x128(8 bits) */
    .dir = 0,
    .raw = 1,
    .raw_out = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 1,
    .addr_base = {(unsigned char *)(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_51_conv_22_zero_off_out_52 */
    .offset_start = 0,
    .offset_end = 129,
    .offset_limit = 192,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 128,
    .frame_loop_cnt = 1,
    .frame_tot_cnt = 1,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(9, &Gemm_51_conv_22_dma_init_in_0_43, 1);

  /* Unit= 0 [STREAM_ENG_V2 0] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_51_conv_22 input ports=1 range=1[142384,143026] */

  static const LL_Streng_TensorInitTypeDef Gemm_51_conv_22_dma_init_in_1_43 = {
    /* 5x1x1x128(8 bits) */
    .dir = 0,
    .raw = 1,
    .continuous = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 0,
    .addr_base = {(unsigned char *)(0x34200000UL) /* Equivalent hex address = 0x34200000UL */}, /* Gemm_51_weights_transposed_21 */
    .offset_start = 142384,
    .offset_end = 143026,
    .offset_limit = 143096,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 0,
    .line_offset = 0,
    .loop_offset = 0,
    .frame_loop_cnt = 0,
    .frame_tot_cnt = 1,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(0, &Gemm_51_conv_22_dma_init_in_1_43, 1);


  /* Dma input bandwidth from memory pools: */
  /* activations_sram -> 128 */
  /* weights_sram -> 640 */

  /* Dma output units from cycle: */
  /* Unit= 2 [STREAM_ENG_V2 2] */
  /* Emit conf for STREAM_ENG_V2 node=Gemm_51_conv_22_off_bias_57 output ports=0 range=0[128,133] */

  static const LL_Streng_TensorInitTypeDef Gemm_51_conv_22_off_bias_57_dma_init_out_0_43 = {
    /* to memory with batch=5 */
    .dir = 1,
    .raw = 1,
    .noblk = 0,
    .align_right = 0,
    .nbits_unsigned = 0,
    .addr_base = {(unsigned char *)(0x34240000UL) /* Equivalent hex address = 0x34240000UL */}, /* Gemm_51_conv_22_off_bias_out_58 */
    .offset_start = 8192,
    .offset_end = 8207,
    .offset_limit = 8271,
    .frame_count = 0,
    .fwidth = 0,
    .fheight = 0,
    .batch_depth = 0,
    .batch_offset = 0,
    .frame_offset = 15,
    .line_offset = 0,
    .loop_offset = 0,
    .frame_loop_cnt = 0,
    .frame_tot_cnt = 1,
    .nbits_in = 24,
    .nbits_out = 24,
  };

  /* Unit=STREAM_ENG_V2 */
  LL_Streng_TensorInit(2, &Gemm_51_conv_22_off_bias_57_dma_init_out_0_43, 1);


  /* Dma output bandwidth to memory pools: */
  /* activations_sram <- 5 */

  static const LL_Switch_InitTypeDef switch_init_in_43[] = {
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 9, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_51_conv_22 IN: in unit=CONV_ACC_V2 0 in port=0 out unit=STREAM_ENG_V2 9 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_51_conv_22 IN: in unit=CONV_ACC_V2 0 in port=1 out unit=STREAM_ENG_V2 0 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, STRENG, 2, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_51_conv_22_off_bias_57 OUT: in unit=STREAM_ENG_V2 2 in port=0 out unit=ARITH_ACC_V2 3 out port=0 */
  };


  /* epoch=43 */
  LL_Switch_Init(switch_init_in_43, 3);

  /* *** MCU cache invalidate (only) operation (HW, whole range) *** */
  /*     memory pool: 0 */
  /*     start: ((uintptr_t)(ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 128))) */
  /*     end:   ((uintptr_t)(ATON_LIB_PHYSICAL_TO_VIRTUAL_ADDR(0x34240000UL + 160))) */
  LL_ATON_Cache_MCU_Invalidate_Range((uintptr_t)0x34242000UL, 15);

  static const LL_ATON_EnableUnits_InitTypeDef Enable_epoch_43_all_units[] = {
    { {STRENG, 2} }, /* STREAM_ENG_V2 */
    { {CONVACC, 0} }, /* CONV_ACC_V2 */
    { {STRENG, 0} }, /* STREAM_ENG_V2 */
    { {STRENG, 9} }, /* STREAM_ENG_V2 */
  };


  LL_ATON_EnableUnits_Init(Enable_epoch_43_all_units, 4);


}

/* SM05 derived epoch43: exact-width candidate, NOT vendor-generated unmodified output. */
static void SM05_End_43(const void *epoch_block)
{
  LL_ATON_LIB_UNUSED(epoch_block);

  static const LL_Switch_DeinitTypeDef switch_deinit_in_43[] = {
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 9, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_51_conv_22 IN: in unit=CONV_ACC_V2 0 in port=0 out unit=STREAM_ENG_V2 9 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, CONVACC, 0, 1), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, STRENG, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_51_conv_22 IN: in unit=CONV_ACC_V2 0 in port=1 out unit=STREAM_ENG_V2 0 out port=0 */
    { LL_Switch_Init_Dest() = ATONN_DSTPORT(STRSWITCH, 0, STRENG, 2, 0), LL_Switch_Init_Source(0) = ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 0, 0), LL_Switch_Init_Context(0) = 1, LL_Switch_Init_Frames(0) = 0, }, /* Gemm_51_conv_22_off_bias_57 OUT: in unit=STREAM_ENG_V2 2 in port=0 out unit=ARITH_ACC_V2 3 out port=0 */
  };


  /* epoch=43 */
  LL_Switch_Deinit(switch_deinit_in_43, 3);

  static const LL_ATON_DisableUnits_InitTypeDef Disable_epoch_43_all_units[] = {
    { {STRENG, 2} }, /* STREAM_ENG_V2 */
    { {CONVACC, 0} }, /* CONV_ACC_V2 */
    { {STRENG, 0} }, /* STREAM_ENG_V2 */
    { {STRENG, 9} }, /* STREAM_ENG_V2 */
  };


  LL_ATON_DisableUnits_Init(Disable_epoch_43_all_units, 4);


}

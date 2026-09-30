/**
  ******************************************************************************
  * @file    nsl_qcfs_seed0.h
  * @author  STEdgeAI
  * @date    2026-09-25 09:43:29
  * @brief   Minimal description of the generated c-implemention of the network
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  ******************************************************************************
  */
#ifndef LL_ATON_NSL_QCFS_SEED0_H
#define LL_ATON_NSL_QCFS_SEED0_H

/******************************************************************************/
#define LL_ATON_NSL_QCFS_SEED0_C_MODEL_NAME        "nsl_qcfs_seed0"
#define LL_ATON_NSL_QCFS_SEED0_ORIGIN_MODEL_NAME   "model_qdq_int8"

/************************** USER ALLOCATED IOs ********************************/
// No user allocated inputs
// No user allocated outputs

/************************** INPUTS ********************************************/
#define LL_ATON_NSL_QCFS_SEED0_IN_NUM        (1)    // Total number of input buffers
// Input buffer 1 -- Input_12_out_0
#define LL_ATON_NSL_QCFS_SEED0_IN_1_ALIGNMENT   (32)
#define LL_ATON_NSL_QCFS_SEED0_IN_1_SIZE_BYTES  (164)

/************************** OUTPUTS *******************************************/
#define LL_ATON_NSL_QCFS_SEED0_OUT_NUM        (1)    // Total number of output buffers
// Output buffer 1 -- Dequantize_53_out_0
#define LL_ATON_NSL_QCFS_SEED0_OUT_1_ALIGNMENT   (32)
#define LL_ATON_NSL_QCFS_SEED0_OUT_1_SIZE_BYTES  (20)

#endif /* LL_ATON_NSL_QCFS_SEED0_H */

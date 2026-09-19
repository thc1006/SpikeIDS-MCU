/**
  ******************************************************************************
  * @file    cpunet.h
  * @date    2026-09-20T03:10:05+0800
  * @brief   ST.AI Tool Automatic Code Generator for Embedded NN computing
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  ******************************************************************************
  */
#ifndef STAI_CPUNET_DETAILS_H
#define STAI_CPUNET_DETAILS_H

#include "stai.h"
#include "layers.h"

const stai_network_details g_cpunet_details = {
  .tensors = (const stai_tensor[5]) {
   { .size_bytes = 11, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {2, (const int32_t[2]){1, 11}}, .scale = {1, (const float[1]){0.024639930576086044}}, .zeropoint = {1, (const int16_t[1]){4}}, .name = "input_output" },
   { .size_bytes = 64, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {2, (const int32_t[2]){1, 64}}, .scale = {1, (const float[1]){0.00823040958493948}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "relu_output" },
   { .size_bytes = 64, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {2, (const int32_t[2]){1, 64}}, .scale = {1, (const float[1]){0.003959858324378729}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "relu_1_output" },
   { .size_bytes = 32, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {2, (const int32_t[2]){1, 32}}, .scale = {1, (const float[1]){0.0018325673881918192}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "relu_2_output" },
   { .size_bytes = 5, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {2, (const int32_t[2]){1, 5}}, .scale = {1, (const float[1]){0.0012466589687392116}}, .zeropoint = {1, (const int16_t[1]){36}}, .name = "output_QuantizeLinear_Input_output" }
  },
  .nodes = (const stai_node_details[4]){
    {.id = 11, .type = AI_LAYER_DENSE_TYPE, .input_tensors = {1, (const int32_t[1]){0}}, .output_tensors = {1, (const int32_t[1]){1}} }, /* relu */
    {.id = 14, .type = AI_LAYER_DENSE_TYPE, .input_tensors = {1, (const int32_t[1]){1}}, .output_tensors = {1, (const int32_t[1]){2}} }, /* relu_1 */
    {.id = 17, .type = AI_LAYER_DENSE_TYPE, .input_tensors = {1, (const int32_t[1]){2}}, .output_tensors = {1, (const int32_t[1]){3}} }, /* relu_2 */
    {.id = 20, .type = AI_LAYER_DENSE_TYPE, .input_tensors = {1, (const int32_t[1]){3}}, .output_tensors = {1, (const int32_t[1]){4}} } /* output_QuantizeLinear_Input */
  },
  .n_nodes = 4
};
#endif


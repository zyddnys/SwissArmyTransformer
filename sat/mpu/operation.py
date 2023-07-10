# -*- encoding: utf-8 -*-
'''
@File    :   operation.py
@Time    :   2023/06/21 17:05:39
@Author  :   Ming Ding 
@Contact :   dm18@mails.tsinghua.edu.cn
'''

# here put the import lib
import os
import sys
import math
import random

import numpy as np
import torch
from sat.mpu import destroy_model_parallel, initialize_model_parallel, get_model_parallel_rank, get_model_parallel_world_size
from sat.mpu import ColumnParallelLinear, RowParallelLinear, VocabParallelEmbedding

def mp_split_checkpoint(path):
    raise NotImplementedError

def mp_merge_checkpoint(path):
    raise NotImplementedError

def mp_split_model(model, new_model_parallel_size):
    """
    This function makes partitions in-place for a model.
    It takes less memory when world size is small.
    """
    from sat.model.transformer import SelfAttention, CrossAttention

    destroy_model_parallel()
    initialize_model_parallel(new_model_parallel_size)
    def iter_repartition(module):
        for name, sub_module in module.named_children():
            if isinstance(sub_module, (ColumnParallelLinear, RowParallelLinear, VocabParallelEmbedding, 
                                       SelfAttention, CrossAttention)):
                sub_module.repartition()
            iter_repartition(sub_module)
    iter_repartition(model)

def mp_split_model_rank0(model, model_full):
    """
    This function loads partitions from rank 0.
    It takes less memory when world size is large.
    """
    def iter_repartition(new_model, module):
        for (new_name, sub_new_model), (name, sub_module) in zip(new_model.named_children(), module.named_children()):
            if isinstance(sub_module, (ColumnParallelLinear, RowParallelLinear, VocabParallelEmbedding)):
                new_weights, new_biases = sub_module.partition()
                for i, w in enumerate(new_weights):
                    if i == 0:
                        sub_new_model.weight.data.copy_(w)
                    else:
                        torch.distributed.send(w.cuda(), i)
                for i, b in enumerate(new_biases):
                    if i == 0:
                        sub_new_model.bias.data.copy_(b)
                    else:
                        torch.distributed.send(b.cuda(), i)
            else:
                for (nn, np), (n, p) in zip(sub_new_model.named_parameters(recurse=False), sub_module.named_parameters(recurse=False)):
                    np.data.copy_(torch.clone(p.data).detach())
                    torch.distributed.broadcast(np.data, 0)
            iter_repartition(sub_new_model, sub_module)
    iter_repartition(model, model_full)

def mp_split_model_receive(model):
    def iter_repartition(module):
        for name, sub_module in module.named_children():
            if isinstance(sub_module, VocabParallelEmbedding):
                torch.distributed.recv(sub_module.weight.data, 0)
            elif isinstance(sub_module, (ColumnParallelLinear, RowParallelLinear)):
                torch.distributed.recv(sub_module.weight.data, 0)
                if sub_module.bias is not None:
                    torch.distributed.recv(sub_module.bias.data, 0)
            else:
                for n, p in sub_module.named_parameters(recurse=False):
                    torch.distributed.broadcast(p.data, 0)
            iter_repartition(sub_module)
    iter_repartition(model)
    
def mp_merge_model(model):
    raise NotImplementedError
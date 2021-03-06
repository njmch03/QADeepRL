import numpy as np
from tqdm import tqdm
import argparse
import json
import math
import os
import shutil
from pprint import pprint
from read_data import read_data, get_squad_data_filter, update_config
from args import parse_args
from model import *

def _config_debug(config):
    if config.debug:
        config.num_steps = 2
        config.eval_period = 1
        config.log_period = 1
        config.save_period = 1
        config.val_num_batches = 2
        config.test_num_batches = 2


def eval_model(model, dev_data, config):

    model.eval()

    loss = 0

    num_steps = int(math.ceil(dev_data.num_examples / (config.batch_size * config.num_gpus)))

#    print("eval steps: ", num_steps)
    for batches in tqdm(dev_data.get_multi_batches(config.batch_size, config.num_gpus,
                                                     num_steps=num_steps, shuffle=True, cluster=config.cluster), total=num_steps):
        model(batches)
        loss += model.build_loss()
        
    return loss.data.cpu().numpy()[0] / num_steps


def main():
    
    config = parse_args()
    data_filter = get_squad_data_filter(config)
    train_data = read_data(config, 'train', config.load, data_filter=data_filter)
    dev_data = read_data(config, 'dev', True, data_filter=data_filter)
    
    update_config(config, [train_data, dev_data])
    _config_debug(config)

    print("Total vocabulary for training is %s" % config.word_vocab_size) 
    word2vec_dict = train_data.shared['lower_word2vec'] if config.lower_word else train_data.shared['word2vec']
    word2idx_dict = train_data.shared['word2idx']
    idx2vec_dict = {word2idx_dict[word]: vec for word, vec in word2vec_dict.items() if word in word2idx_dict}

    # if Glove use the vector, otherwise, assigns random value
    emb_mat = np.array([idx2vec_dict[idx] if idx in idx2vec_dict
                        else np.random.multivariate_normal(np.zeros(config.word_emb_size), np.eye(config.word_emb_size))
                        for idx in range(config.word_vocab_size)])

    config.emb_mat = emb_mat

    ## Initialize model
    model = BiDAF(config)

    if config.use_gpu:
        model.cuda()

    optimizer = optim.Adagrad(filter(lambda p: p.requires_grad, model.parameters()), lr=0.5)

    ## Begin training
    num_steps = config.num_steps or int(math.ceil(train_data.num_examples / (config.batch_size * config.num_gpus))) * config.num_epochs
    global_step = 0

    print(num_steps)
    
    count = 1
    train_loss = []
    for batches in tqdm(train_data.get_multi_batches(config.batch_size, config.num_gpus,
                                                     num_steps=num_steps, shuffle=True, cluster=config.cluster), total=num_steps):
            
        model.train()
        model.zero_grad()
        
        model(batches)
        loss = model.build_loss()

        loss.backward()
        optimizer.step()

        if count % 100 == 0:
            eval_loss = eval_model(model, dev_data, config)
            print("train loss is: %.3f" % loss.data.cpu().numpy()[0])
            print("eval loss is: %.3f \n" % eval_loss)
            model.train()

        count += 1
    return 


    #count = 0
    #for idx, ds in train_data.get_batches(config.batch_size, num_batches=None, shuffle=False, cluster=False):
    #    if count > 0:
    #        break
        #for i in idx:
            #print(i)
            #print(ds.data)
    #    count += 1
    #return


if __name__ == "__main__":
    main()

from Network import Network
from environment import UltimateTTT
from player import AlphaZeroPlayer, MCTSPlayer, Player, RandomPlayer
from policy import RandomPolicy
from tqdm import tqdm
from termcolor import colored
import torch
import torch.nn as nn
import torch.optim as optim
import matplotlib.pyplot as plt
import numpy as np
import pickle
import random

# set random seed
random.seed(1234)
torch.manual_seed(1234)
np.random.seed(1234)

'''
history: list of (state, probability) pair
split_rate: controls the train/validation set split rate
shuffle: a switch to indicate whether the dataset should be shuffled
output training features, training labels, validation features, validation labels
'''
def to_dataset(history, split_rate = 0.7, shuffle = True):
    # shuffle the data
    if shuffle:
        random.shuffle(history)


    board_batch = []
    prob_batch = []
    for board, prob in history:
        board_batch.append(board[None])
        prob_batch.append(prob)
    
    board_batch = np.array(board_batch)
    prob_batch = np.array(prob_batch)

    # get the board and prob batch data in tensors
    board_batch = torch.from_numpy(board_batch)
    prob_batch = torch.from_numpy(prob_batch)

    # split into training/validation datasets
    split = int(len(history)*split_rate)
    train_board = board_batch[:split]
    val_board = board_batch[split:]

    train_prob = prob_batch[:split]
    val_prob = prob_batch[split:]

    return train_board, train_prob, val_board, val_prob

'''
Given a batch dataset and a size
Output a list of mini-batches specified by the mini-batch size
'''
def to_mini_batch(dataset, mini_size):
    batch = []
    dim = dataset.size()[0]
    for index in range(0,dim,mini_size):
        batch.append(dataset[index:index+mini_size])
    
    return batch


'''
let the player play game with itself
input a player and its copy
output the dataset generated by the game
'''
def self_play(player1:MCTSPlayer,player2:MCTSPlayer):
    game = UltimateTTT(player1,player2)
    game.play()
    hist1 = player1.get_history()
    hist2 = player2.get_history()
    data = hist1 + hist2
    player1.reset()
    player2.reset()
    return data

'''
cross-entropy loss of move probabilities
'''
def loss_function(pi, p):
    cel = nn.CrossEntropyLoss()
    pol_loss = cel(pi,p)
    
    return pol_loss


'''
Given a current best player, a baseline player and the number of games to play
Output the game result as a dictionary
'''
def eval(current_best:Player, baseline:Player, num_games = 20):
    result = {'win':0, 'lose':0, 'draw':0}
    print(colored("Evaluation in progress:",'green'))
    for i in tqdm(range(num_games)):
        # alternating x and o
        if i % 2 == 0:
            game = UltimateTTT(current_best, baseline)
            game.play()
            final_state = game.get_state()
            if final_state['winner'] == 1:
                result['win'] += 1
            elif final_state['winner'] == -1:
                result['lose'] += 1
            else:
                result['draw'] += 1
        else:
            game = UltimateTTT(baseline, current_best)
            game.play()
            final_state = game.get_state()
            if final_state['winner'] == -1:
                result['win'] += 1
            elif final_state['winner'] == 1:
                result['lose'] += 1
            else:
                result['draw'] += 1
        
        # reset both players if needed
        if type(current_best).__name__ == 'MCTSPlayer' or type(current_best).__name__ == 'AlphaZeroPlayer':
            current_best.reset()
        if type(baseline).__name__ == 'MCTSPlayer' or type(baseline).__name__ == 'AlphaZeroPlayer':
            baseline.reset()
    
    return result

'''
given the number of self-play games and checkpoint
generate more game data through self play and store the data per checkpoint number of games
'''
def generate_dataset(num_self_play=100, checkpoint = 5):
    # make players
    pol = RandomPolicy()
    sim = RandomPlayer()
    player = MCTSPlayer(pol, sim, store_hist=True)
    player_cpy = MCTSPlayer(pol, sim, store_hist=True)
    dataset = None

    # open exsiting dataset if there is one
    try:
        with open('dataset.txt','rb') as fp:
            dataset = pickle.load(fp)
        print(colored(f"Dataset file loaded. Currently has {len(dataset)} data points. Continue generating data.","green"))
    except FileNotFoundError:
        dataset = []
        print(colored('Cannot find dataset file. Start from the beginning.','blue'))
    
    # generate game data
    for game_num in tqdm(range(num_self_play)):
        if game_num % checkpoint == 0:
            with open('dataset.txt', 'wb') as fp:
                pickle.dump(dataset,fp)
        
        data = self_play(player, player_cpy)
        dataset.extend(data)
    
    # save the dataset at the end
    with open('dataset.txt', 'wb') as fp:
        pickle.dump(dataset,fp)


'''
num_epoch: number of epoch for each batch of data
mini_size: size of mini-batch
lr: learning rate
load_model: load model to continue if True, start afresh otherwise
'''
def train(num_epoch = 100, mini_size = 20, lr = 1e-4, load_model = False):


    model = None
    train_loss = []
    val_loss = []

    # try loading the dataset
    try:
        with open('dataset.txt','rb') as fp:
            dataset = pickle.load(fp)
            print(colored('Dataset successfully loaded.','green'))
    except FileNotFoundError:
        print(colored('Cannot find dataset. Training aborted.','red'))
        return

    # check if load an existin model
    if load_model:
        model = torch.load('model.pt')
        print(colored('Model successfully loaded.', 'green'))

    else:
        print(colored('Training the network from fresh.','blue'))
        model = Network()

    # initialize optimizer
    optimizer = optim.Adam(model.parameters(),lr)

    print(colored('Start training process:', 'green'))

    # get batch and split into mini-batches    
    train_board, train_prob, val_board, val_prob = to_dataset(dataset)

    mini_board = to_mini_batch(train_board, mini_size)
    mini_prob = to_mini_batch(train_prob, mini_size)


    best_val_loss = float('inf')
    best_epoch = -1
    # training the network
    for epoch in tqdm(range(num_epoch)):
        for index in range(len(mini_board)):
            board = mini_board[index]
            pi = mini_prob[index]

            p = model(board)
            optimizer.zero_grad()
            loss = loss_function(pi,p)
            loss.backward()
            optimizer.step()
        
        # compute training loss
        train_predict = model(train_board)
        loss_train = loss_function(train_prob, train_predict).item()
        train_loss.append(loss_train)

        # compute validation loss
        val_predict = model(val_board)
        loss_val = loss_function(val_prob, val_predict).item()
        val_loss.append(loss_val)

        # update best model
        if loss_val < best_val_loss:
            best_val_loss = loss_val
            best_epoch = epoch
            torch.save(model, 'model.pt')
        
    print(colored(f'The best validation loss is {best_val_loss}.','cyan'))
    print(colored(f'The epoch of the best validation loss is {best_epoch}.','cyan'))

    # saving the loss records
    with open('train_loss.txt', 'wb') as fp:
        pickle.dump(train_loss,fp)    
    with open('val_loss.txt', 'wb') as fp:
        pickle.dump(val_loss, fp)

'''
plot the learning curves of the neural network
'''
def plot_figure():
    plt.figure()
    with open('train_loss.txt','rb') as fp:
        train_loss = pickle.load(fp)
        plt.plot(range(1,len(train_loss)+1), train_loss, label='Training Loss')
        
    
    with open('val_loss.txt','rb') as fp:
        val_loss = pickle.load(fp)
        plt.plot(range(1,len(val_loss)+1), val_loss, label="Validation Loss") 

    plt.title('Learning Curve of the Deep Neural Network')
    plt.xlabel('Epochs')
    plt.ylabel('Mean Cross Entropy Loss')
    plt.legend()
    plt.grid()
    plt.savefig('learning_curve.jpg')
    plt.show()


def main():
    # generate_dataset()
    # train()
    # plot_figure()
    rand_player = RandomPlayer()
    pol = RandomPolicy()
    mcts_player = MCTSPlayer(pol,rand_player)
    alpha_player = AlphaZeroPlayer()
    
    result = eval(alpha_player, mcts_player)
    print(f"Number of wins: {result['win']}")
    print(f"Number of losts: {result['lose']}")
    print(f"Number of draws: {result['draw']}")

    

if __name__ == '__main__':
    main()
import numpy as np
import torch
from neural_net import Network

class Policy:
    def get_probs(self, state:dict):
        pass

class NNPolicy(Policy):
    def __init__(self, NNet:Network):
        self.network = NNet
    
    '''
    take state as an input
    output the re-normalized probabilities of each valid move in a list
    '''
    def get_probs(self, state: dict):
        valid_moves = state['valid_move']
        board = state['inner']*state['current']
        board = board[None,None]
        board_state = torch.from_numpy(board)
        move_probs = self.network(board_state)

        valid_move_probs = []
        total_valid_probs = 0

        for move in valid_moves:
            valid_prob = move_probs[0][move].item()
            valid_move_probs.append(valid_prob)
            total_valid_probs += valid_prob
        
        valid_move_probs = torch.Tensor(valid_move_probs)
        sum = torch.sum(valid_move_probs)
        if (sum != 0):
            valid_move_probs = valid_move_probs/sum

        return valid_move_probs


class RandomPolicy(Policy):
    '''
    input a state
    output a vector of equal probabilities corresponding to the dimension of valid moves
    '''
    def get_probs(self, state: dict):
        length = len(state['valid_move'])
        probs = np.ones(length)/length
        return probs

import environment as env
import numpy as np
import random
import pns_tt
import signal


WIN = 1
DRAW = 0
LOSS = -1
# The class for one TreeNode
class TreeNode:
    '''
    game_state: the current game state the tree node stores
    policy: a function that maps game states to action probabilities, used as prior
    simulation_player: the player that is used in simulation step
    '''
    def __init__(self,game_state: dict, policy, simulation_player, depth = 0, timelimit = 5):
        # essential components of a tree
        self.state = game_state
        self.policy = policy
        self.sim_player = simulation_player
        self.priors = self.policy.get_probs(game_state)
        self.edges = {}
        for i, move in enumerate(game_state['valid_move']):
            self.edges[move] = {'prior':self.priors[i], 'count':0, 'total_val':0, 'node':None}
        
        # properties
        self.is_terminal = self.state['game_end']
        self.proof = None
        self.best_move = None
        self.depth = depth
        self.timelimit = timelimit

        signal.signal(signal.SIGALRM, self.handler)
    
    # update proof based on its children
    def update_proof(self):
        # ignore this if self is already (dis)proved
        if self.proof is not None:
            return

        # store the moves corresponding to their current outcome
        loss, tie, unknown = [],[],[]
        for move, edge in self.edges.items():
            if edge['node'] is None:
                # the node has not been grown yet
                unknown.append(move)
            else:
                # get the node
                node:TreeNode = edge['node']
                # not yet (dis)proved
                if node.proof is None:
                    unknown.append(move)
                # opponent is winning, self is
                # losing
                elif node.proof == WIN:
                    loss.append(move)
                # tie
                elif node.proof == DRAW:
                    tie.append(move)
                # opponent is losing, self is
                # winning
                elif node.proof == LOSS:
                    # only need one winning move
                    self.proof = WIN
                    self.best_move = move
                    return

        # all child node outcomes have been decided
        # now
        if len(unknown) == 0:
            # The best it can do is tie
            if len(tie) > 0:
                self.proof = DRAW
                self.best_move = random.choice(tie)
                return
            else:
                self.proof = LOSS
                return

    '''
    unroll from the node till the end of the game
    return the game winner
    x win: 1
    o win: -1
    draw: 2
    '''
    def unroll(self):
        if self.is_terminal:
            # at terminal state
            # update the proof if the state itself is terminal
            if self.state['winner'] == self.state['current']:
                self.proof = WIN
            elif self.state['winner'] == 2:
                self.proof = DRAW
            else:
                self.proof = LOSS

            # return the winner of the state
            return self.state['winner']
        elif self.proof is not None:
            # The node is already (dis)proved
            if self.proof == WIN:
                return self.state['current']
            elif self.proof == DRAW:
                return 2
            else:
                return self.state['current']*-1        
        elif self.depth >= 62:
            # state is deep enough to do a pns to check for exact win
            game = env.UltimateTTT(self.sim_player, self.sim_player, self.state, False)
            try:
                signal.alarm(self.timelimit)
                pnstt_agent = pns_tt.PNSTT(game, self.state['current'], exact=True)
                winning, _ = pnstt_agent.run()
                signal.alarm(0)
            except:
                # time out, playout randomly instead
                game.play()
                return game.winner

            # wins exactly store the best move
            if winning:
                self.proof = WIN
                self.best_move = pnstt_agent.next_best_move()
                return self.state['current']
            else:
            # not winning, random playout
                game.play()
                return game.winner
        
        else:
            # use MC playouts
            game = env.UltimateTTT(self.sim_player, self.sim_player, self.state, False)
            game.play()
            return game.winner

    '''
    get a list of actions that have the max values
    exploration_factor: controls the level of exploration, the higher, the more exploration and vice-versa
    prioritize the nodes that have not been expanded before
    randomly sample one action from the candidates in case of a tie
    return the sampled acton
    '''
    def get_max_action(self,explore_factor):
        # return the best move if it has one
        if self.best_move is not None:
            return self.best_move

        # get total visit of this node
        total_visit = 0
        for _, value in self.edges.items():
            total_visit += value['count']
        # store maximum value
        max_val = float('-inf')
        # store max actions
        max_actions = []
        for action, record in self.edges.items():
            # if the edge is never visited before
            if record['count'] == 0:
                # if the previous are visited edges
                if max_val < float('inf'):
                    max_val = float('inf')
                    max_actions = [action]
                else:
                    max_actions.append(action)
            # if the edge if visited before
            else:
                q = record['total_val']/record['count']
                u = explore_factor*record['prior']*np.sqrt(total_visit)/(1+record['count'])
                # if the value is the current max
                if q+u > max_val:
                    max_val = q+u
                    max_actions = [action]
                # if it is equal the current max
                elif q+u == max_val:
                    max_actions.append(action)
        
        # choose action to simulate
        action = np.random.choice(max_actions)

        return action

    '''
    simulate and (possibly) grow the tree once
    return the simulation result
    x win: 1
    o win: -1
    tie: 2 
    '''
    def simulate(self, explore_factor):
        # check if current is terminal state
        if self.is_terminal:
            return self.state['winner']
        
        # get the max action
        action = self.get_max_action(explore_factor)

        # get the edge of that action
        edge = self.edges[action]

        # grow the edge if it does not exist
        if edge['node'] is None:
            # get the updated state
            game = env.UltimateTTT(self.sim_player,self.sim_player,self.state)
            game.update_game_state(action)
            new_state = game.get_state()

            # create new tree node
            new_node = TreeNode(new_state, self.policy, self.sim_player, self.depth + 1, self.timelimit)
            edge['node'] = new_node
            
            # unroll the new_node once
            result = new_node.unroll()

            # initialize counter
            edge['count'] = 1

            # update value
            # if result is not tie
            if result != 2:
                current_player = self.state['current']
                # initialize value using the result
                # positive if same sign, negative otherwise
                edge['total_val'] = result*current_player
            
            # update the proof once it finishes growing the child node
            self.update_proof()

            # return the simulation result
            return result
        # simulate next node if it exists
        else:
            result = edge['node'].simulate(explore_factor)
            edge['count'] += 1
            if result != 2:
                current_player = self.state['current']
                # increment total_val based on the result
                edge['total_val'] += result*current_player
            
            # update the proof
            self.update_proof()
            return result

    def handler(self, signum, fram):
        raise TimeoutError("Timed out.")

    '''
    input a state
    check if the state is identical to the state of itself
    '''
    def equal_state(self, state:dict):
        
        this_state = self.state
        input_state = state

        # if the inner boards have any difference
        if (this_state['inner'] != input_state['inner']).any():
            return False
               
        # if the current players are not the same
        if this_state['current'] != input_state['current']:
            return False
        
        
        # if the winners are not the same
        if this_state['winner'] != input_state['winner']:
            return False
        
        # if the previous moves are not the same
        if this_state['previous'] != input_state['previous']:
            return False
        
        # the two states are identical
        return True


# Monte Carlo Tree Search Class
class MCTSPNS:
    # initialze attributes
    def __init__(self, state:dict, policy, simulation_player, exploration_factor = 0.5, timelimit = 5) -> None:
        self.root = TreeNode(state, policy, simulation_player, self.count_step(state['inner']), timelimit)
        self.pol = policy
        self.sim_player = simulation_player
        self.explore_factor = exploration_factor
        self.timelimit = timelimit
    

    '''
    input number of simulation steps
    run simulations from the root (current) state
    '''
    def run_simumation(self, num = 600):
        # only run simulation when there is no best move
        if self.root.best_move is None:
            for _ in range(num):
                self.root.simulate(self.explore_factor)

    '''
    compute the probability distributions for candidate moves
    sample an action from the distribution
    return both the action and the probability disitribution of moves over the entire output space (81 slots)
    ATTENTION: this method also changes the root node to the lastest game state resulted after taking the action provided it's not None
    '''
    def get_move(self):
        step = self.root.depth
        if self.root.best_move is not None:
            '''
            use the already found best move
            '''
            move = self.root.best_move
            probs = np.zeros(81)
            probs[move] = 1
            # move the root to the next
            self.root = self.root.edges[move]['node']
            # increase the count for already proved node
            return move, probs, 'pre-proven'
        elif step >= 45:
            '''
            try to solve exactly with PNS
            '''
            try:
                # create game
                game = env.UltimateTTT(None, None, self.root.state, False)
                # create agent
                pnstt_agt = pns_tt.PNSTT(game, self.root.state['current'], False)
                # perform PNS with the time limit
                signal.alarm(self.timelimit)
                res = pnstt_agt.search()
                signal.alarm(0)
                # if there is winning move
                if res:
                    move = pnstt_agt.next_best_move()   
                    if move is not None:
                        probs = np.zeros(81)
                        probs[move] = 1
                        # move the root to the next
                        self.root = self.root.edges[move]['node']
                        return move, probs, 'proven'
            except:
                pass

        # either the search exceeds running time or there is no winning move
        '''
        use the visit count to find give the best move
        '''
        actions = []
        visit_count = []
        # store the actions and the corresponding visit counts
        for key, value in self.root.edges.items():
            actions.append(key)
            visit_count.append(value['count'])
        
        visit_count = np.array(visit_count)
        
        # get the action probabilities
        probs = visit_count/np.sum(visit_count)

        # sample next move
        move = np.random.choice(actions, p = probs)

        # the probabilities over the entire output dimension
        prob_vec = np.zeros(81)
        prob_vec[actions] = probs

        # move the root to the next
        self.root = self.root.edges[move]['node']
        
        return move, prob_vec, 'simulated'
    
    '''
    update the root node based on the input state:
    if the state is already simulated by the tree before, then just change the root node to the corresponding node
    otherwise, create a new node and make it the root (typically happens when there is a new game)
    '''
    def transplant(self, state:dict):
        if self.root is not None:
            # get the previous move for faster locationing
            prev_move = state['previous']
            if prev_move is not None:
                target_node = self.root.edges[prev_move]['node']
                if target_node is not None and target_node.equal_state(state):
                    self.root = target_node
                    return
        
        # either the previous move is None or the target node is not matching
        new_node = TreeNode(state,self.pol,self.sim_player, self.count_step(state['inner']))
        self.root = new_node
    
    def count_step(self, board):
        '''
        count the number of pieces into the game
        '''
        total = 0
        for row in board:
            for piece in row:
                if piece != 0:
                    total += 1
        
        return total

        

        

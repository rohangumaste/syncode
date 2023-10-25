from collections import defaultdict
import time
import interegular
import torch

class TerminalsNFA:
    """
    We build an NFA that consists of DFAs for each terminal. We simulate the NFA by consuming the input string for each terminal DFA.
    """
    def __init__(self, terminals: list, vocab):
        self._terminals_to_dfa = {}
        self._vocab = vocab
        self.anything_else = interegular.fsm.anything_else # This is special character used for the DFAs

        for terminal in terminals:
            self._terminals_to_dfa[terminal.name] = interegular.parse_pattern(terminal.pattern.to_regexp()).to_fsm()
        
        # Iterate through each pair of DFA state and next terminals and store the overapproximate tokens
        self._dfa_state_and_next_terminal_to_tokens = defaultdict(list)
        self._store_overapproximate_tokens(self._terminals_to_dfa.keys(), vocab)


    def _store_overapproximate_tokens(self, terminals: list[str], vocab):
        for cur_terminal in terminals:
            for dfa_state in self._terminals_to_dfa[cur_terminal].states:
                # self._dfa_state_and_next_terminal_to_tokens[(dfa_state, next_terminal)] = []
                for token_idx, token in enumerate(vocab):
                    is_valid, remainder = self._consume_prefix(self._terminals_to_dfa[cur_terminal], dfa_state, token)

                    # if cur_terminal == 'FLOAT_NUMBER' and token == ' +': for debugging
                    #     print(is_valid, remainder, dfa_state, self._terminals_to_dfa[cur_terminal].finals)
                    if not is_valid:
                        continue
                        
                    if remainder is None:
                        # We reached a live state for the current terminal, thus we add the token in all overapproximate sets of next terminals
                        for next_terminal in terminals:
                            self._dfa_state_and_next_terminal_to_tokens[(cur_terminal, dfa_state, next_terminal)].append(token_idx)
                    else:
                        # We reached the final state while consuming the token, thus we conusme the remainder with all next terminals
                        for next_terminal in terminals:
                            next_terminal_dfa = self._terminals_to_dfa[next_terminal]
                            is_valid, _ = self._consume_prefix(next_terminal_dfa, next_terminal_dfa.initial, remainder)
                            if is_valid: 
                                # We reached a live state for the next terminal, thus we add the 
                                # token in the  overapproximate sets of next terminal
                                self._dfa_state_and_next_terminal_to_tokens[(cur_terminal, dfa_state, next_terminal)].append(token_idx)
        

    def _consume_prefix(self, dfa: interegular.FSM, dfa_state, input_str):
        """
        Consume longest prefix of s that is accepted by dfa and return the remainder. 
        If we reach a dead state, return (False, None). 
        If the consumption ends at any live state that is not an accept state, return (True, None).
        If we reach a final state, return (True, remainder).
        """
        state = dfa_state
        longest_accept_index = -1

        if state in dfa.finals:
            longest_accept_index = 0

        for i, symbol in enumerate(input_str):
            if symbol == ' ': # ignore spaces
                continue

            if not symbol in dfa.alphabet:
                if not self.anything_else in dfa.alphabet:
                    state = None
                    break
                symbol = self.anything_else

            # Missing transition = transition to dead state
            if not (state in dfa.map and dfa.alphabet[symbol] in dfa.map[state]):
                state = None
                break

            state = dfa.map[state][dfa.alphabet[symbol]]

            if state in dfa.finals:
                longest_accept_index = i+1
        
        if longest_accept_index != -1: # reached accept state at some point
            return (True, input_str[longest_accept_index:])
        elif state != None and dfa.islive(state): # if state is a live state
            return (True, None)
        
        # if we never reach a final state and reach a dead state at some point
        return (False, None)

    def _consume_input(self, dfa, input_str):
        """
        Conumses the input string and returns the final state if it is live, otherwise returns None
        """
        dfa_state = dfa.initial

        for i, symbol in enumerate(input_str):
            if not symbol in dfa.alphabet:
                if not self.anything_else in dfa.alphabet:
                    return None
                symbol = self.anything_else
            # Missing transition = transition to dead state
            if not (dfa_state in dfa.map and dfa.alphabet[symbol] in dfa.map[dfa_state]):
                return None
            dfa_state = dfa.map[dfa_state][dfa.alphabet[symbol]]
            
        return dfa_state


    def _nfa_state(self, input_str):
        """
        consume input_str and get the list of pairs of (terminal, dfa_state). This denotes our current NFA state
        """
        nfa_state = []
        for (termianl, dfa) in self._terminals_to_dfa.items():
            # print(termianl)
            dfa_state = self._consume_input(dfa, input_str)
            if dfa_state is not None:
                nfa_state.append((termianl, dfa_state)) 
        return nfa_state
    
    def _convert_lookup_from_list_to_mask(self):
        for key, val in self._dfa_state_and_next_terminal_to_tokens.items():
            self._dfa_state_and_next_terminal_to_tokens[key] = self._get_tokens_mask(val)

    def get_overapprox_tokens_mask(self, cur_incomplete_string, next_terminals: list, get_list=False):
        start_time = time.time()
        cur_nfa_state = self._nfa_state(cur_incomplete_string)
        # print(cur_nfa_state)
        overapprox_token_ids = torch.zeros(len(self._vocab), dtype=torch.bool)
        # print('Time taken for NFA state:', time.time() - start_time, flush=True)
        for (cur_terminal, dfa_state) in cur_nfa_state:
            for next_terminal in next_terminals:
                overapprox_token_ids |= self._dfa_state_and_next_terminal_to_tokens[(cur_terminal, dfa_state, next_terminal)]

        # print('Time taken for union:', time.time() - start_time, flush=True)
        if get_list: # This is useful for testing
            return self._get_tokens_list(overapprox_token_ids)
        # print('Time taken for mask to list:', time.time() - start_time, flush=True)
        return overapprox_token_ids
    
    def _get_tokens_mask(self, tokens_idx_list) -> torch.Tensor:
        indices = torch.tensor(tokens_idx_list)
        tokens_mask = torch.zeros(len(self._vocab), dtype=torch.bool)
        tokens_mask[indices] = 1
        return tokens_mask

    def _get_tokens_list(self, token_mask) -> list[str]:
        return [self._vocab[idx.item()] for idx in torch.where(token_mask == True)[0]]
    
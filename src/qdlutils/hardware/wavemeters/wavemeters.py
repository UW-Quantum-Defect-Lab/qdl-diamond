class WavemeterController:

    '''
    This is a base class which represents a wavemeter software controller. All other wavemeter
    controllers should inherit this structure, although additional complexity can be added on top.

    The existence of these functions is assumed in other parts of the code where a wavemeter is
    utilized.
    '''

    def __init__(
            self,
            *args,
            **kwargs
    ):
        '''
        Initialization function. Saves parameters and sets up functionality.
        '''
        raise NotImplementedError('This is the base class.')
    
    def open(self):
        '''
        Opens the connection to the wavemeter
        '''
        raise NotImplementedError('This is the base class.')
    
    def close(self):
        '''
        Closes the connection to the wavemeter, freeing it for use in other applications
        '''
        raise NotImplementedError('This is the base class.')
    
    def readout(self):
        '''
        Outputs the current value on the wavemeter in standard numeric datatypes (float, int).
        '''
        raise NotImplementedError('This is the base class.')
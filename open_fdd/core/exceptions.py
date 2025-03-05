class MissingColumnError(Exception):
    """Exception raised when required columns are missing from the DataFrame."""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class InvalidParameterError(Exception):
    """Exception raised when parameters are invalid."""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

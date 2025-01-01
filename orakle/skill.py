class Skill:
    def __init__(self):
        self.name = self.__class__.__name__

    def start(self):
        raise NotImplementedError("This method should be overridden by subclasses")

    def stop(self):
        raise NotImplementedError("This method should be overridden by subclasses")

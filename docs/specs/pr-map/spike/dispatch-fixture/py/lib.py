class A:
    def save(self):
        return 1


class B:
    def save(self):
        return 2


def store(obj):
    return obj.save()


store(A())

from agricatch.management.commands import localizr

class Command(localizr.Command):
    def handle(self,*args, **options):
        localizr.Command.handle(self,*args, **options)
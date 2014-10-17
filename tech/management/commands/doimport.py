from agricatch.management.commands import doimport

class Command(doimport.Command):
    def handle(self,*args, **options):
        doimport.Command.handle(self,*args, **options)
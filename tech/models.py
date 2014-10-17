from django.db import models, IntegrityError
import datetime

class Article(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.TextField()
    description = models.TextField()
    link = models.CharField(max_length=512L, blank=True)
    time = models.DateTimeField(null=True, blank=True)
    added_at = models.DateTimeField(default=datetime.datetime.now)
    author = models.CharField(max_length=128L, blank=True)
    hash = models.CharField(max_length=64L, unique=True)
    website = models.ForeignKey('Website', null=True, db_column='website', blank=True)

    def save(self, *args, **kwargs):
        import hashlib
        gen_hash = hashlib.sha224('|'.join([self.name,self.time]).encode('utf-8')).hexdigest()
        self.hash = gen_hash

        try:
            super(Article, self).save(*args, **kwargs)
        except IntegrityError, e:
            self = Article.objects.get(hash=self.hash)


    class Meta:
        db_table = 'article'
        

class Website(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=64L)
    slug = models.CharField(max_length=128L, unique=True)
    address = models.CharField(max_length=512L)
    class Meta:
        db_table = 'website'

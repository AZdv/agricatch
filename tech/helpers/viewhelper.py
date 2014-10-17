from tech.models import Article
import os,time

def _query_and_write_last_update(file_path,last_update_file):
    """Checking the last added Article, and saving the timestamp into file (yes yes, Memcached, I know)"""
    last_event = Article.objects.latest('added_at')
    result = last_event.added_at.strftime('%Y-%m-%d %H:%M:%S')
    fp = open(file_path + last_update_file,'w')
    fp.write(result)


def get_last_update(file_path,last_update_file,update_every=2):
    """
    file_path - e.g. assets/
    last_update_file - e.g. file.txt
    update_every - number of hours it takes the before query call (default 2)
    """
    try:
        with open(file_path+last_update_file) as file:
            time_passed = time.time() - os.path.getmtime(file_path+last_update_file)
            hours_passed = time_passed / 3600
            if (hours_passed > update_every):
                _query_and_write_last_update(file_path,last_update_file)

    except IOError:
        _query_and_write_last_update(file_path,last_update_file)
    
    with open(file_path+last_update_file) as file:
        result = file.read()
    
    return result
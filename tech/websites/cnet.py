from agricatch.website import Website
class Cnet(Website):
    def __init__(self):
        Website.__init__(self)
        
        self.website_slug = 'cnet'
        self.type = 'Article'
        self.url_info = {
                     'url' : 'http://feeds.feedburner.com/cnet/NnTv',
                     'days_on_page' : 1
        }
        
        self.structure = {
                      'child_xpath' : '//item',
                      'fields' : {
                              'name' : {
                                    'type' : 'normal',
                                    'xpath' : 'title'
                              },
                              'description' : {
                                    'type' : 'normal',
                                    'xpath' : 'description'
                              },
                              'link' : {
                                    'type' : 'normal',
                                    'xpath' : 'link'
                              },
                              'author' : {
                                    'type' : 'normal',
                                    'xpath' : 'creator'
                              },
                              'time' : {
                                    'type' : 'time',
                                    'format' : '%STR%',  # %STR% - current text field
                                    'xpath' : 'pubdate',
                              }
                              
                      }
                          
        }
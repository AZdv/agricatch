from agricatch.website import Website
class Techcrunch(Website):
    def __init__(self):
        Website.__init__(self)
        
        self.website_slug = 'techcrunch'
        self.type = 'Article'
        self.url_info = {
                     'url' : 'http://feeds.feedburner.com/TechCrunch',
                     'days_on_page' : 1
        }
        
        self.structure = {
                      #'pagination' : '//div[@id="Results"]/div[contains(@class,"location")]/a[contains(@href,"a_page=")]',
                      'child_xpath' : '//channel/item',
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
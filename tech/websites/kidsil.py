from agricatch.website import Website
class Kidsil(Website):
    def __init__(self):
        Website.__init__(self)
        
        self.website_slug = 'kidsil'
        self.type = 'Article'
        self.url_info = {
                     'url' : 'http://www.kidsil.net', #kidsil has a feed, but we want to use some more complex functions days_on_page
                     'here' : 1
        }
        
        self.structure = {
                      #'pagination' : '//div[@id="Results"]/div[contains(@class,"location")]/a[contains(@href,"a_page=")]',
                      'child_xpath' : '//div[@id="content-blog"]/div[contains(@class,"post")]',
                      'fields' : {
                              'name' : {
                                    'type' : 'normal',
                                    'xpath' : 'h1[contains(@class,"post-title")]'
                              },
                              'description' : {
                                    'type' : 'normal',
                                    'xpath' : 'div[contains(@class,"post-entry")]'
                              },
                              'image' : {
                                    'type' : 'normal',
                                    'xpath' : 'div[contains(@class,"post-entry")]/*/img/@src'
                              },
                              'link' : {
                                    'type' : 'normal',
                                    'xpath' : 'h1[contains(@class,"post-title")]/a/@href'
                              },
                              'author' : {
                                    'type' : 'normal',
                                    'xpath' : 'div[contains(@class,"post-meta")]/*[starts-with(@class,"author")]'
                              },
                              'time' : {
                                    'type' : 'time',
                                    'format' : '%STR%',  # %STR% - current text field
                                    'xpath' : 'div[contains(@class,"post-meta")]/*/*[contains(@class,"timestamp")]',
                              }
                              
                      }
                          
        }
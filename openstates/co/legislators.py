from billy.scrape import ScrapeError, NoDataForPeriod
from billy.scrape.legislators import LegislatorScraper, Legislator
from billy.scrape.committees  import Committee

import lxml.html
import re, contextlib

CO_BASE_URL = "http://leg.colorado.gov/"

CTTY_BLACKLIST = [ # Invalid HTML causes us to snag these tags. Super annoying.
    "Top",
    "State Home",
    "Colorado Legislature"
]


def clean_committee(name):
    committee_name = name.replace("&", " and ")
    return re.sub("\s+", " ", committee_name).strip()


def clean_input( line ):
    if line != None:
        return re.sub( " +", " ", re.sub( "(\n|\r)+", " ", line ))


class COLegislatorScraper(LegislatorScraper):
    jurisdiction = 'co'

    def _get_latest_session_from_term(self, term):
        '''Determines latest session from metadata.'''
        sessions = [s for s in [t for t in self.metadata['terms'] if t['name']\
            == term][-1]['sessions']]

        # We're assuming the last session in the term is the current one.
        latest_session = sessions[-1]

        return latest_session

    def _get_district_list(self, chamber, session):
        chamber = {
            "upper" : "2",
            "lower" : "1"
        }[chamber]

        url = "http://leg.colorado.gov/legislators?field_chamber_target_id=" + chamber + \
            "&field_political_affiliation_target_id=All&sort_bef_combine=field_last_name_value%20ASC"

        return url

    def scrape_directory(self, next_page, chamber, session):
        '''Download a list of legislators and parse out the people there.'''
        ret = {}
        html = self.get(next_page).text
        page = lxml.html.fromstring(html)
        rows = page.xpath( "//table[@id='legislators-overview-table']/tbody/tr" )
        for row in rows:
            ele = row.xpath( "./td/a" )[0]
            url = CO_BASE_URL + ele.attrib['href']
            ret[row.text] = url

        return ret

    def parse_homepage( self, hp_url ):
        ''' Parse out profile details (image, committees) from legislator detail pages.'''
        image_base = "http://www.state.co.us/gov_dir/leg_dir/senate/members/"
        ret = []
        obj = {}
        image = ""
        html = self.get(hp_url).text
        page = lxml.html.fromstring(html)
        page.make_links_absolute(hp_url)

        email = page.xpath("//a[contains(@href, 'mailto')]")[0]
        email = email.attrib['href']
        email = email.split(":", 1)[1]
        obj['email'] = email

        infoblock = page.xpath("//div[@align='center']")
        info = infoblock[0].text_content()

        number = re.findall("(\d{3})(-|\))?(\d{3})-(\d{4})", info)
        if len(number) > 0:
            number = number[0]
            number = "%s %s %s" % (
                number[0],
                number[2],
                number[3]
            )
            obj['number'] = number
        ctty_apptmts = [clean_input(x) for x in
                         page.xpath("//a[contains(@href, 'CLC')]//font/text()")]

        new = []
        for entry in ctty_apptmts:
            if "--" in entry:
                ctty, _ = entry.split("--")
                new.append(ctty.strip())

        ctty_apptmts = filter(lambda x: x.strip() != "" and
                              x not in CTTY_BLACKLIST, new)

        (image,) = page.xpath("//img[contains(@src, '.jpg') or\
                                contains(@src, '.jpeg') or\
                                contains(@src, '.png')]/@src")
        obj.update({
            "ctty"  : ctty_apptmts,
            "photo" : image
        })
        return obj

    def process_person( self, p_url ):
        '''Scrapes a legislator detail page, such as http://leg.colorado.gov/legislators/irene-aguilar '''
        ret = { "homepage" : p_url }

        html = self.get(p_url).text
        page = lxml.html.fromstring(html)
        page.make_links_absolute(p_url)

        info = page.xpath( '//div[@class="main-content-section"]' )[0]
        main = info.xpath( './main' )[0]
        sidebar = info.xpath( './aside' )[0]
        leg_info = main.xpath( './article/div/div[@class="legislator-content"]/div' ) # Returns 2-3 elements.

        ret['party'] = leg_info[1].xpath( './div[@class="field-items"]/div' )[0].text_content()

        person_name = clean_input(main.xpath( './article/header/h1' )[0].text_content())
        ret['name'] = clean_input(re.sub( '\(.*$', '', person_name).strip())
        ret['occupation']  = clean_input(leg_info[0].xpath( './div[@class="field-items"]/div' )[0].text_content())

        urls = page.xpath( '//a' )
        ret['photo_url'] = main.xpath( './article/div[@class="legislator-body"]/div[@class="legislator-profile-picture"]/div/div/div/img' )[0].attrib['src']
        #ret['homepage'] = home_page.attrib['href'].strip()

        ret['ctty'] = main.xpath( './div/div/div/div/div[@class="committee-assignment"]' )
        email = sidebar.xpath( './div/div[@id="block-cga-legislators-legislator-contact"]/div/div/div/div[@class="contact-email"]/a' )[0].attrib['href']
        ret['email'] = email.replace('mailto:', '')
        ret['number'] = sidebar.xpath( './div/div[@id="block-cga-legislators-legislator-contact"]/div/div/div/div[@class="contact-phone"]/div/div[@class="field-items"]/div' )[0].text_content()
        return ret

    def scrape(self, chamber, term):
        session = self._get_latest_session_from_term(term)
        url = self._get_district_list(chamber, session)
        people_pages = self.scrape_directory(url, chamber, session)

        for person in people_pages:
            district = person
            p_url = people_pages[district]
            metainf = self.process_person(p_url)

            p = Legislator(term, chamber, district, metainf['name'],
                party=metainf['party'],
                # some additional things the website provides:
                occupation=metainf['occupation'],
                photo_url=metainf['photo_url'],
                url=metainf['homepage'])

            phone = metainf['number'] if 'number' in metainf else None
            email = metainf['email'] if 'email' in metainf else None
            p.add_office(
                'capitol',
                'Capitol Office',
                phone=phone,
                address='200 E. Colfax\nDenver, CO 80203',
                email=email)

            p.add_source(p_url)
            self.save_legislator(p)

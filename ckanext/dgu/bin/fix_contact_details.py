'''
Resets package contact details for packages which have the same contact details as their group (due to UI bug)
'''

import os
import sys
from sqlalchemy import engine_from_config
from pylons import config
import common
from optparse import OptionParser

from running_stats import StatsList


def package_is_effected(package, group):
    return ((package.extras.get('contact-name') == group.extras.get('contact-name')) and
            (package.extras.get('contact-email') == group.extras.get('contact-email')) and
            (package.extras.get('contact-phone') == group.extras.get('contact-phone')) and
            (package.extras.get('foi-name') == group.extras.get('foi-name')) and
            (package.extras.get('foi-email') == group.extras.get('foi-email')) and
            (package.extras.get('foi-web') == group.extras.get('foi-name')) and
            (package.extras.get('foi-phone') == group.extras.get('foi-phone')))

class FixContactDetails(object):
    @classmethod
    def load_config(cls, path):
        import paste.deploy
        conf = paste.deploy.appconfig('config:' + path)
        import ckan
        ckan.config.environment.load_environment(conf.global_conf,
                conf.local_conf)

    @classmethod
    def command(cls, config_ini, write):
        stats = StatsList()

        config_ini_filepath = os.path.abspath(config_ini)
        cls.load_config(config_ini_filepath)
        common.register_translator()
        engine = engine_from_config(config, 'sqlalchemy.')

        from ckan import model
        
        model.init_model(engine)    
        rev = model.repo.new_revision()
        rev.author = 'fix_contact_details.py'

        for package in model.Session.query(model.Package):
            try:
                group = package.get_groups()[0]
                if not group.extras.get('foi-name'):
                    continue
            except:
                continue

            if package.extras.get('contact-name') == group.extras.get('contact-name'):
                if package_is_effected(package, group):
                    if write:
                        package.extras['contact-name'] = ''
                        package.extras['contact-email'] = ''
                        package.extras['contact-phone'] = ''
                        package.extras['foi-name'] = ''
                        package.extras['foi-email'] = ''
                        package.extras['foi-web'] = ''
                        package.extras['foi-phone'] = ''
                    stats.add('resetting', 'Resetting package %s' % package.name)

        print stats.report()
        if write:
            model.Session.commit()


def usage():
    print """
Resets package contact details for packages which have the same contact details as their group (due to UI bug)
Usage:

    python fix_contact_details.py <CKAN config ini filepath>
    """

if __name__ == '__main__':
    parser = OptionParser(usage='')
    parser.add_option("-w", "--write",
                      action="store_true",
                      dest="write",
                      default=False,
                      help="write the changes to the datasets")
    (options, args) = parser.parse_args()
    if len(args) != 1:
        usage()
        sys.exit(0)
    config_ini = args[0]
    FixContactDetails.command(config_ini, options.write)

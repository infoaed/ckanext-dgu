'''
Daily script for gov server
'''
import os
import logging
import sys
import zipfile
import traceback
import datetime
import re
import urllib2
import json

from common import load_config, register_translator

start_time = datetime.datetime.today()
def report_time_taken(log):
    time_taken = (datetime.datetime.today() - start_time).seconds
    log.info('Time taken: %i seconds' % time_taken)

def get_db_config(config): # copied from fabfile
    url = config['sqlalchemy.url']
    # e.g. 'postgres://tester:pass@localhost/ckantest3'
    db_details_match = re.match('^\s*(?P<db_type>\w*)://(?P<db_user>\w*):?(?P<db_pass>[^@]*)@(?P<db_host>[^/:]*):?(?P<db_port>[^/]*)/(?P<db_name>[\w.-]*)', url)

    db_details = db_details_match.groupdict()
    return db_details

def command(config_file):
    # Import ckan as it changes the dependent packages imported
    from dump_analysis import get_run_info, TxtAnalysisFile, CsvAnalysisFile, DumpAnalysisOptions, DumpAnalysis
    
    from pylons import config

    # settings
    ckan_instance_name = os.path.basename(config_file).replace('.ini', '')
    if ckan_instance_name not in ['development', 'dgutest']:
        default_dump_dir = '/var/lib/ckan/%s/static/dump' % ckan_instance_name
        default_analysis_dir = '/var/lib/ckan/%s/static/dump_analysis' % ckan_instance_name
        default_backup_dir = '/var/backups/ckan/%s' % ckan_instance_name
        default_openspending_reports_dir = '/var/lib/ckan/%s/openspending_reports' % ckan_instance_name
    else:
        # test purposes
        default_dump_dir = '~/dump'
        default_analysis_dir = '~/dump_analysis'
        default_backup_dir = '~/backups'
        default_openspending_reports_dir = '~/openspending_reports'
    dump_dir = os.path.expanduser(config.get('ckan.dump_dir',
                                             default_dump_dir))
    analysis_dir = os.path.expanduser(config.get('ckan.dump_analysis_dir',
                                             default_analysis_dir))
    backup_dir = os.path.expanduser(config.get('ckan.backup_dir',
                                               default_backup_dir))
    openspending_reports_dir = os.path.expanduser(config.get('dgu.openspending_reports_dir',
                                                             default_openspending_reports_dir))
    dump_filebase = config.get('ckan.dump_filename_base',
                               'data.gov.uk-ckan-meta-data-%Y-%m-%d')
    dump_analysis_filebase = config.get('ckan.dump_analysis_base',
                               'data.gov.uk-analysis')
    backup_filebase = config.get('ckan.backup_filename_base',
                                 ckan_instance_name + '.%Y-%m-%d.pg_dump')
    tmp_filepath = config.get('ckan.temp_filepath', '/tmp/dump.tmp')
    openspending_reports_url = config.get('ckan.openspending_reports_url',
                                          'http://data.etl.openspending.org/uk25k/report/')


    log = logging.getLogger('ckanext.dgu.bin.gov_daily')
    log.info('----------------------------')
    log.info('Starting daily script')
    start_time = datetime.datetime.today()

    import ckan.model as model
    import ckan.lib.dumper as dumper

    # Check database looks right
    num_packages_before = model.Session.query(model.Package).count()
    log.info('Number of existing packages: %i' % num_packages_before)
    if num_packages_before < 2:
        log.error('Expected more packages.')
        sys.exit(1)
    elif num_packages_before < 2500:
        log.warn('Expected more packages.')

    # Copy openspending reports
    log.info('Copying in OpenSpending reports')
    if not os.path.exists(openspending_reports_dir):
        log.info('Creating dump dir: %s' % openspending_reports_dir)
        os.makedirs(openspending_reports_dir)
    try:
        publisher_response = urllib2.urlopen('http://data.gov.uk/api/rest/group').read()
    except urllib2.HTTPError, e:
        log.error('Could not get list of publishers for OpenSpending reports: %s',
                  e)
    else:
        try:
            publishers = json.loads(publisher_response)
            assert isinstance(publishers, list), publishers
            assert len(publishers) > 500, len(publishers)
            log.info('Got list of %i publishers starting: %r',
                     len(publishers), publishers[:3])
        except Exception, e:
            log.error('Could not decode list of publishers for OpenSpending reports: %s',
                      e)
        else:
            urls = [openspending_reports_url]
            for publisher in publishers:
                urls.append('%spublisher-%s.html' % (openspending_reports_url, publisher))
            for url in urls:
                try:
                    report_response = urllib2.urlopen(url).read()
                except urllib2.HTTPError, e:
                    if e.code == 404:
                        log.info('Got 404 for openspending report %s' % url)
                    else:
                        log.error('Could not download openspending report %r: %s',
                                  url, e)
                else:
                    report_html = report_response
                    # remove header
                    report_html = report_html.split('---')[-1]
                    # add date
                    report_html += '<p class="import-date">Page imported from <a href="http://openspending.org/">OpenSpending</a> on %s</p>' % \
                                   datetime.datetime.now().strftime('%d-%m-%Y')
                    # add <html>
                    report_html = '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:i18n="http://genshi.edgewall.org/i18n" '\
                                  'xmlns:py="http://genshi.edgewall.org/" xmlns:xi="http://www.w3.org/2001/XInclude" '\
                                  'py:strip="">' + report_html + '</html>'
                    # & encoding
                    report_html = report_html.replace(' & ', ' &amp; ')
                    report_html = report_html.replace('(GBP)', '(&pound;)')
                    try:
                        report_html_encoded = report_html #.encode('utf8', 'ignore')
                    except UnicodeDecodeError, e:
                        import pdb; pdb.set_trace()
                    # save it
                    filename = url[url.rfind('/')+1:] or 'index.html'
                    filepath = os.path.join(openspending_reports_dir, filename)
                    f = open(filepath, 'wb')
                    try:
                        f.write(report_html_encoded)
                    finally:
                        f.close()
                    log.info('Wrote openspending report %s', filepath)

    # Create dumps for users
    log.info('Creating database dump')
    if not os.path.exists(dump_dir):
        log.info('Creating dump dir: %s' % dump_dir)
        os.makedirs(dump_dir)
    query = model.Session.query(model.Package)
    dump_file_base = start_time.strftime(dump_filebase)
    logging.getLogger("MARKDOWN").setLevel(logging.WARN)
    for file_type, dumper_ in (('csv', dumper.SimpleDumper().dump_csv),
                              ('json', dumper.SimpleDumper().dump_json),
                             ):
        dump_filename = '%s.%s' % (dump_file_base, file_type)
        dump_filepath = os.path.join(dump_dir, dump_filename + '.zip')
        tmp_file = open(tmp_filepath, 'w')
        log.info('Creating %s file: %s' % (file_type, dump_filepath))
        dumper_(tmp_file, query)
        tmp_file.close()
        dump_file = zipfile.ZipFile(dump_filepath, 'w', zipfile.ZIP_DEFLATED)
        dump_file.write(tmp_filepath, dump_filename)
        dump_file.close()
    report_time_taken(log)

    # Dump analysis
    log.info('Creating dump analysis')
    if not os.path.exists(analysis_dir):
        log.info('Creating dump analysis dir: %s' % analysis_dir)
        os.makedirs(analysis_dir)
    json_dump_filepath = os.path.join(dump_dir, '%s.json.zip' % dump_file_base)
    txt_filepath = os.path.join(analysis_dir, dump_analysis_filebase + '.txt')
    csv_filepath = os.path.join(analysis_dir, dump_analysis_filebase + '.csv')
    run_info = get_run_info()
    options = DumpAnalysisOptions(analyse_by_source=True)
    analysis = DumpAnalysis(json_dump_filepath, options)
    log.info('Saving dump analysis')
    output_types = (
        # (output_filepath, analysis_file_class)
        (txt_filepath, TxtAnalysisFile),
        (csv_filepath, CsvAnalysisFile),
        )
    analysis_files = {} # analysis_file_class, analysis_file
    for output_filepath, analysis_file_class in output_types:
        log.info('Saving dump analysis to: %s' % output_filepath)
        analysis_file = analysis_file_class(output_filepath, run_info)
        analysis_file.add_analysis(analysis.date, analysis.analysis_dict)
        analysis_file.save()
    report_time_taken(log)

    # Create complete backup
    log.info('Creating database backup')
    if not os.path.exists(backup_dir):
        log.info('Creating backup dir: %s' % backup_dir)
        os.makedirs(backup_dir)

    db_details = get_db_config(config)
    pg_dump_filename = start_time.strftime(backup_filebase)
    pg_dump_filepath = os.path.join(backup_dir, pg_dump_filename)
    cmd = 'export PGPASSWORD=%(db_pass)s&&pg_dump ' % db_details
    for pg_dump_option, db_details_key in (('U', 'db_user'),
                                           ('h', 'db_host'),
                                           ('p', 'db_port')):
        if db_details.get(db_details_key):
            cmd += '-%s %s ' % (pg_dump_option, db_details[db_details_key])
    cmd += '%(db_name)s' % db_details + ' > %s' % pg_dump_filepath
    log.info('Backup command: %s' % cmd)
    ret = os.system(cmd)
    if ret == 0:
        log.info('Backup successful: %s' % pg_dump_filepath)
        log.info('Zipping up backup')
        pg_dump_zipped_filepath = pg_dump_filepath + '.gz'
        # -f to overwrite any existing file, instead of prompt Yes/No
        cmd = 'gzip -f %s' % pg_dump_filepath 
        log.info('Zip command: %s' % cmd)
        ret = os.system(cmd)
        if ret == 0:
            log.info('Backup gzip successful: %s' % pg_dump_zipped_filepath)
        else:
            log.error('Backup gzip error: %s' % ret)
    else:
        log.error('Backup error: %s' % ret)

    # Log footer
    report_time_taken(log)
    log.info('Finished daily script')
    log.info('----------------------------')

if __name__ == '__main__':
    USAGE = '''Daily script for government
    Usage: python %s [config.ini]
    ''' % sys.argv[0]
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h'):
        err = 'Error: Please specify config file.'
        print USAGE, err
        logging.error('%s\n%s' % (USAGE, err))
        sys.exit(1)
    config_file = sys.argv[1]
    config_ini_filepath = os.path.abspath(config_file)

    load_config(config_ini_filepath)
    register_translator()
    logging.config.fileConfig(config_ini_filepath)
    
    command(config_file)

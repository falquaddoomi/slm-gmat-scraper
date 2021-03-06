import json
import subprocess

from datetime import datetime, timedelta

from billiard import Process
from celery.schedules import crontab
from dateutil.parser import parse
from celery import Celery, group
from celery.utils.log import get_task_logger

from twisted.internet import reactor
from scrapy.utils.project import get_project_settings

from gmat_collector import app
from gmat_collector.models import db, Student, Practice, VeritasAccount

import scrapy
from scrapy.utils.serialize import ScrapyJSONEncoder
from scrapy.signals import item_scraped, spider_closed
from scrapy.crawler import CrawlerProcess, Crawler

from gmat_collector.scrapers.account_creator import VeritasAccountCreator
from gmat_collector.scrapers.veritas import VeritasScraper

SCRAPE_BACKOFF_MINUTES = 30 # amount of minutes after scraping to not re-scrape a user's data

# =====================================================================================================================
# === general celery app configuration
# =====================================================================================================================

def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)

    celery.Task = ContextTask
    return celery


app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379/1',
    CELERY_RESULT_BACKEND='redis://localhost:6379/1',
    CELERY_DEFAULT_QUEUE='gmat_queue',
    # CELERYD_MAX_TASKS_PER_CHILD=1,
    CELERYBEAT_SCHEDULE={
        'scrape-all-students': {
            'task': 'gmat_collector.tasks.scrape_all_students',
            'schedule': crontab(minute='*/%d' % SCRAPE_BACKOFF_MINUTES)
        },
    },
    # because apparently everything else is insecure :|
    CELERY_ACCEPT_CONTENT=['json'],
    CELERY_TASK_SERIALIZER='json',
    CELERY_RESULT_SERIALIZER='json',

    BROKER_TRANSPORT_OPTIONS={
        'fanout_prefix': True,
        'fanout_patterns': True,
        'visibility_timeout': 43200
    }
)
celery = make_celery(app)

logger = get_task_logger(__name__)


# =====================================================================================================================
# === scrapy helpers
# =====================================================================================================================

BASE = "/home/ec2-user/projects/gmat_collector/"
SCRAPY_BIN = "%s/.venv/bin/scrapy" % BASE
SPIDER_FILE = "%s/gmat_collector/scrapers/veritas.py" % BASE
ACCT_SPIDER_FILE = "%s/gmat_collector/scrapers/account_creator.py" % BASE

scrapy_encoder = ScrapyJSONEncoder()


def runSubprocScraper(spider_file, username, password):
    cmd = "%(cmd)s runspider %(spider_file)s -L DEBUG --logfile veritas_spider.log -a username=%(username)s -a password=%(password)s -o - -t json" % {
        'cmd': SCRAPY_BIN,
        'spider_file': spider_file,
        'username': username,
        'password': password
    }
    subproc_out = subprocess.check_output(cmd.split())
    print "Subprocess output: %s" % subproc_out

    try:
        json_data = json.loads(subproc_out)
        return json_data
    except ValueError as ex:
        # FIXME: if scrapy doesn't yield anything, it just emits a single [ without a closing ]; why does it do that?
        print "WARN when parsing subproc response: %s" % str(ex)
        return []


def runSpiderProcess(spider_cls, *args, **kwargs):
    """
    Helper method that starts a spider with the given init arguments, waits for it to complete, and returns the
    items it yielded in a list.
    :param spider_cls: the spider class to run
    :param args: the indexed arguments to the spider
    :param kwargs: the keyword arguments to the spider
    :return: a list of items yielded by the spider
    """
    process = CrawlerProcess()
    process.crawl(spider_cls, *args, **kwargs)

    final_result = []

    def _nab_item(item):
        # FIXME: this silly dance of encoding and decoding is to prevent scrapy items from being returned to celery
        # FIXME: celery can't serialize them, so it throws a rather opaque error, but it's fine with lists and dicts
        final_result.append(json.loads(scrapy_encoder.encode(item)))

    for crawler in process.crawlers:
        crawler.signals.connect(_nab_item, item_scraped)

    process.start()
    process.stop()

    return final_result


# =====================================================================================================================
# === task definitions
# =====================================================================================================================

@celery.task()
def ping():
    print "ping() called, sending pong..."
    return "pong!"


@celery.task()
def associate_veritas_account(student_id, username, password):
    student = Student.query.get(student_id)

    print "About to get credentials for student %d..." % student_id

    # results = runSpider(VeritasAccountCreator, username, password)
    results = runSubprocScraper(ACCT_SPIDER_FILE, username, password)

    try:
        creds = results[0]

        print "Received credentials: %s" % str(creds)

        # create a veritasaccount model and associate it with this student
        account = VeritasAccount(student=student, email=creds['email'], password=creds['password'])
        db.session.add(account)
        db.session.commit()

        return creds

    except IndexError or ValueError:
        logger.warn("Couldn't create account for student ID %d, continuing..." % student_id)
        return None


@celery.task()
def scrape_veritas(username, password):
    print "About to scrape for student w/username %s..." % username
    # results = runSpider(VeritasScraper, username, password)
    results = runSubprocScraper(SPIDER_FILE, username, password)
    print "Got results for username %s: %s" % (username, results)

    return results


def gen_fingerprint(student_id, taken_on, question_count, percent_correct, duration):
    return "%s-%s-%s-%s-%s" % (student_id, taken_on.strftime("%Y.%m.%d"), question_count, percent_correct, duration)


@celery.task()
def update_student(practice_set, student_id):
    student = Student.query.get(student_id)
    inserted = 0

    for p in practice_set:
        taken_on = parse(p['taken_on'])
        generated_print = gen_fingerprint(student_id, taken_on, p['question_count'], p['percent_correct'], p['duration'])

        if student.practices.filter(Practice.fingerprint == generated_print).count() <= 0:
            db.session.add(Practice(
                student=student,
                taken_on=taken_on,
                question_count=p['question_count'],
                percent_correct=p['percent_correct'],
                duration=p['duration'],
                fingerprint=generated_print,
                site_practice_id=p['site_practice_id']
            ))
            inserted += 1

    # mark us as having been scraped and commit it
    student.last_scraped = datetime.now()
    db.session.commit()

    return inserted


@celery.task()
def scrape_all_students(force=False):
    # iterate through each student, launching a scrape task if they've not been scraped recently
    pending_students = Student.query.filter(
        (Student.account != None) & (
            (Student.last_scraped == None) |
            (datetime.now() - Student.last_scraped > timedelta(minutes=SCRAPE_BACKOFF_MINUTES))
        )
    ) if not force else Student.query

    print "Scraping practice sessions for %d/%d students!" % (pending_students.count(), Student.query.count())

    # create a group of acquire->store chains, which will all be executed in parallel
    tasks = group(scrape_veritas.s(student.account.email, student.account.password) | update_student.s(student.id)
                  for student in pending_students)
    tasks.delay()


# ===
# === maintenance task to update practices with the site ID, just so we have it
# ===

@celery.task()
def update_student_practice_id(practice_set, student_id):
    """
    For the given student and practice set, find existing practices in the database and update their site_practice_id field
    to what we gather from the site.
    :param practice_set: the set of scrapy items representing practices from veritas
    :param student_id: the id of the student to update
    :return: the number of rows that were updated for the student
    """
    student = Student.query.get(student_id)
    updated = 0

    for p in practice_set:
        taken_on = parse(p['taken_on'])
        generated_print = gen_fingerprint(student_id, taken_on, p['question_count'], p['percent_correct'], p['duration'])

        # find an existing record in the db for this user by its fingerprint
        existing_practices = student.practices.filter(Practice.fingerprint == generated_print)
        practice_count = existing_practices.count()

        if practice_count == 1:
            target_practice = existing_practices.first()
            target_practice.site_practice_id = p['site_practice_id']
            db.session.add(target_practice)
            updated += 1
        elif practice_count < 1:
            print "WARNING: no practices found with matching fingerprint"
        elif practice_count > 1:
            print "ERROR: more than one practice found with a matching fingerprint -- %d, in fact!" % practice_count

    # mark us as having been scraped and commit it
    # actually, we don't care that they've been scraped
    # student.last_scraped = datetime.now()
    db.session.commit()

    return updated


@celery.task()
def update_all_students_site_id():
    # iterate through each student, launching a scrape task if they've not been scraped recently
    pending_students = Student.query

    print "Update practice site IDs for %d/%d students!" % (pending_students.count(), Student.query.count())

    # create a group of acquire->store chains, which will all be executed in parallel
    tasks = group(scrape_veritas.s(student.account.email, student.account.password) | update_student_practice_id.s(student.id)
                  for student in pending_students)
    tasks.delay()

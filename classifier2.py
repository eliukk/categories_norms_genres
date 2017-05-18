#!/usr/bin/env python3
#  -*- coding: UTF-8 -*-
"""
Poem classifier, refactored to process single XML file at once
"""
import argparse
import glob
import logging
import pprint
import re
import csv
import gc
from collections import defaultdict

import pandas
from lxml import etree

import numpy as np
from sklearn.externals import joblib
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.linear_model import SGDClassifier
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline

from classifier import parse_metadata_from_path, get_paper_name_by_issn
from poem_reader import read_xml_directory, parse_text_lines, block_xpath

logging.basicConfig(filename='classifier.log',
                    filemode='a',
                    level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

log = logging.getLogger(__name__)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="Textblock classifier to poems and other text")
    argparser.add_argument("directory", help="Directory to classify")
    argparser.add_argument("--newfile", help="Create new CSV file", dest='newfile', action='store_true')
    args = argparser.parse_args()

    log.info('Loading classifier from pickle file')
    clf = joblib.load('svm.pkl')

    log.info('Classifier loaded')

    if args.directory[-1] != '/':
        args.directory += '/'

    files = glob.glob(args.directory + "**/*.xml", recursive=True)

    if not files:
        log.warning('No files found for %s' % args.directory)
        quit()
    else:
        log.info('Found %s XML files' % len(files))

    if args.newfile:
        with open('foundpoems/found_poems.csv', 'w', newline='') as fp:
            writer = csv.writer(fp, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(('Poem', 'Year', 'Month', 'Day', 'Newspaper name', 'ISSN'))
            log.info('Created new CSV file')

    issues = pandas.read_csv('data/issue_numbers.csv', sep=',')

    filegroup = defaultdict(list)
    filenamesplitter = r'(.*)/[a-zA-Z0-9\-\_]+\.xml'

    for filename in files:
        if 'alto' not in filename:
            continue
        split = re.search(filenamesplitter, filename)
        if split:
            file_prefix = split.groups()
            filegroup[file_prefix].append(filename)

    print(len(filegroup))

    xmls = []
    for issue, issue_files in filegroup.items():
        data = []
        metadata = []
        for filename in issue_files:

            parsed = None
            with open(filename, 'r') as f:
                try:
                    parsed = etree.parse(f)
                    log.debug('Read file %s' % filename)
                except etree.XMLSyntaxError:
                    log.error('Error in XML: %s' % filename)

            if not parsed:
                continue

            text_blocks = block_xpath(parsed)
            paper_metadata = parse_metadata_from_path(filename)

            for block in text_blocks:
                data.append(parse_text_lines(list(block)))
                metadata.append(paper_metadata + (block.get('ID'),))

        data_orig = data
        data = [d.replace('\n', ' ') for d in data]

        # log.debug('Doing prediction')

        predicted = clf.predict(data)

        data_trunc = tuple(d for i, d in enumerate(data_orig) if predicted[i] and len(d) >= 94)
        metadata = tuple(d for i, d in enumerate(metadata) if predicted[i] and len(data_orig[i]) >= 94)

        # log.debug('Prediction done, writing results to files.')

        if not data_trunc:
            continue

        with open('foundpoems/found_poems.csv', 'a', newline='') as fp:
            writer = csv.writer(fp, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

            poemtext = ''
            prev_vector = None
            blockids = []
            year, month, day, issn, blockid, paper = (0, 0, 0, 0, 0, 0)

            for i, d in enumerate(data_trunc):

                year, month, day, issn, blockid = metadata[i]

                paper = get_paper_name_by_issn(issues, issn)

                if prev_vector == (year, month, day, issn):
                    if poemtext:
                        poemtext += "\n"
                    poemtext += d
                    blockids.append(blockid)
                else:
                    if poemtext:
                        year2, month2, day2, issn2 = prev_vector
                        paper2 = get_paper_name_by_issn(issues, issn2)

                        writer.writerow([poemtext.replace('\n', ' '), year2, month2, day2, paper2, issn2])

                        poem_filename = 'foundpoems/{year}_{month}_{day}_{paper} {blocks}'.\
                                        format(year=year2, month=month2, day=day2, paper=paper2, blocks=' '.join(blockids))
                        poem_filename = (poem_filename[:240] + ' TRUNCATED') if len(poem_filename) > 247 else poem_filename
                        poem_filename += '.txt'
                        with open(poem_filename, 'w', newline='') as textp:
                            textp.write(poemtext)
                            log.debug('Written poem to file %s' % poem_filename)

                    poemtext = d
                    blockids = [blockid]

                prev_vector = (year, month, day, issn)

            if year:
                writer.writerow([poemtext.replace('\n', ' '), year, month, day, paper, issn])
                log.debug('Updated CSV file')

                poem_filename = 'foundpoems/{year}_{month}_{day}_{paper} {blocks}'.\
                                format(year=year, month=month, day=day, paper=paper, blocks=' '.join(blockids))
                poem_filename = (poem_filename[:240] + ' TRUNCATED') if len(poem_filename) > 247 else poem_filename
                poem_filename += '.txt'

                with open(poem_filename, 'w', newline='') as textp:
                    textp.write(poemtext)
                    log.debug('Written poem to file %s' % poem_filename)

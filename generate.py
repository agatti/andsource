#!/usr/bin/env python

# Copyright (c) 2012-2013 Alessandro Gatti
#
# This program is licensed under the Eclipse Public License - v 1.0
# You can read the full licence text at
# http://www.eclipse.org/org/documents/epl-v10.html

import argparse
import concurrent.futures
import datetime
import logging
import multiprocessing
import os
import shutil
import stat
import sys
import tempfile
import time
import zipfile


def parse_arguments():  # {{{
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--force', '-f', action='store_true',
                        help='Remove old site if present')
    parser.add_argument('--verbose', '-v', action='count',
                        help='Add logging messages')
    parser.add_argument('--zip', '-z', action='store_true',
                        help='Create a ZIP package instead of a site')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Do not print any message')
    parser.add_argument('--threads', '-t', metavar='THREADS_COUNT',
                        type=int, action='store',
                        help='Concurrent threads to use (defaults to %d)' \
                        % multiprocessing.cpu_count())
    parser.add_argument('sdk_base', metavar='ANDROID_SDK_DIRECTORY',
                        type=str, nargs=1, help='Android SDK directory')
    parser.add_argument('target', metavar='TARGET_LOCATION',
                        type=str, nargs=1,
                        help='Target location for the update site')
    parser.add_argument('version', metavar='VERSION',
                        type=str, nargs=1,
                        help='Plugin version without timestamp')
    return parser.parse_args()
# }}}


DESCRIPTION = 'Android Sources Eclipse plugin site generator'
ASSETS = os.path.dirname(sys.argv[0])
ARGUMENTS = parse_arguments()
NOW = datetime.datetime.now()
VARS = {
    'TIMESTAMP': int(time.mktime(NOW.timetuple())),
    'YEAR': NOW.year
}


def split_property_line(line):  # {{{
    key = ''
    current_line = ''
    in_key = True
    escaped = False
    hex_code = False
    hex_string = ''
    for character in line:
        if hex_code:
            if len(hex_string) == 4:
                current_line += str(int(hex_string, 16))
                hex_code = False
                hex_string = ''
            else:
                if character not in '0123456789ABCDEF':
                    return None
                hex_string += character
                continue
        elif escaped:
            if character in ':=':
                escaped = False
                current_line += character
                continue
            if character == 'u':
                hex_code = True
                hex_string = ''
                escaped = False
                continue

        if character == '\\':
            escaped = True
            continue
        elif character in ':=':
            if not in_key:
                return None

            key = current_line.strip()
            current_line = ''
        else:
            if escaped:
                current_line += '\\'
                escaped = False
            current_line += character

    if not key:
        return None

    return (key, current_line.strip())
# }}}


def parse_property_file(name):  # {{{
    values = {}

    with open(name, 'r') as handle:
        is_continuing = False
        line_buffer = ''
        for source_line in handle.readlines():
            line = source_line.strip()
            if not line:
                continue

            if not is_continuing:
                if line.startswith('#') or line.startswith('!'):
                    continue

            if line.endswith('\\'):
                is_continuing = True
                line_buffer += ' ' + line
                continue

            is_continuing = False
            line = line_buffer + ' ' + line
            line_buffer = ''

            data = split_property_line(line)
            if not data:
                raise Exception('Invalid property found in' + line)

            (key, value) = data
            values[key] = value

    return values
# }}}


def collect_android_sources(base_directory):  # {{{
    source_directories = {}

    sources = os.path.join(base_directory, 'sources')
    if not os.path.exists(sources):
        raise Exception(sources + ' does not exist!')

    for directory in os.listdir(sources):
        source_directory = os.path.join(sources, directory)
        properties_file = os.path.join(source_directory,
                                       'source.properties')
        properties = parse_property_file(properties_file)
        api_level = properties.get('AndroidVersion.ApiLevel', None)
        if not api_level or not api_level.isdigit():
            continue
        api_level = int(api_level)
        if api_level in source_directories:
            raise Exception('Duplicated API level: ' + api_level)

        logging.info('Found sources for API Level %d', api_level)
        source_directories[api_level] = source_directory

    return source_directories
# }}}


def package_sdk_source(directory, target_file):  # {{{
    root_directory = os.path.abspath(directory)

    with zipfile.ZipFile(target_file, 'w', zipfile.ZIP_DEFLATED) as output:
        for root, directories, files in os.walk(directory):
            for directory_name in directories:
                full_directory = os.path.join(root, directory_name)
                os.path.relpath(full_directory, root_directory)

            for file_name in files:
                source_file = os.path.join(root, file_name)
                target_file = os.path.relpath(source_file, root_directory)
                if target_file == 'source.properties':
                    continue

                output.write(source_file, target_file,
                             zipfile.ZIP_DEFLATED)
# }}}


def preprocess(source_file, variables):  # {{{
    output = ''
    with open(source_file, 'r') as handle:
        for line in handle.readlines():
            while '%%' in line:
                start_marker = line.index('%%')
                end_marker = line.index('%%', start_marker + 2)
                variable = line[start_marker + 2:end_marker]
                if variable in variables:
                    line = '%s%s%s' % (line[:start_marker],
                                       str(variables[variable]),
                                       line[end_marker + 2:])
            output += line

    return output
# }}}


def create_target(target_directory, force):  # {{{
    if force and os.path.exists(target_directory):
        logging.info('Removing %s', target_directory)
        shutil.rmtree(target_directory)

    if os.path.exists(target_directory):
        raise Exception('Target directory already exists')

    logging.info('Creating %s', target_directory)

    os.mkdir(target_directory)
    os.mkdir(os.path.join(target_directory, 'features'))
    os.mkdir(os.path.join(target_directory, 'plugins'))
# }}}


def generate_site(base, target, variables):  # {{{
    logging.info('Generating site.xml')

    with open(os.path.join(target, 'site.xml'), 'wb+') as output:
        path = os.path.join(base, 'assets', 'site.xml')
        output.write(bytes(preprocess(path, variables), 'UTF-8'))
# }}}


def generate_content(base, target, variables):  # {{{
    logging.info('Generating content.jar')

    with zipfile.ZipFile(os.path.join(target, 'content.jar'), 'w',
                         zipfile.ZIP_DEFLATED) as output:
        path = os.path.join(base, 'assets', 'content.xml')
        output.writestr('content.xml', preprocess(path, variables),
                        zipfile.ZIP_DEFLATED)
# }}}


def generate_features(base, target, variables):  # {{{
    logging.info('Generating feature jar')

    base_dir = os.path.join(base, 'assets', 'features')
    output_file_name = os.path.join(target, 'features',
                                    'com.android.ide.eclipse.source_' +
                                    variables['VERSION'] + '.jar')
    with zipfile.ZipFile(output_file_name, 'w',
                         zipfile.ZIP_DEFLATED) as output:
        xml_path = os.path.join(base_dir, 'feature.xml')
        output.writestr('feature.xml', preprocess(xml_path, variables),
                        zipfile.ZIP_DEFLATED)
        properties_path = os.path.join(base_dir, 'features.properties')
        output.writestr('feature.properties',
                        preprocess(properties_path, variables),
                        zipfile.ZIP_DEFLATED)

    return os.stat(output_file_name)[stat.ST_SIZE]
# }}}


def generate_plugins(base, target, variables, sdks, threads):  # {{{
    logging.info('Generating plugins jar')

    sdk_archives = {}

    def asynchronous_packer(api_level, path):
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            package_sdk_source(path, temporary)
            logging.info('Packaged SDK %s with filename %s', api_level,
                         temporary.name)
            sdk_archives[api_level] = temporary

    packing_threads = []

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=threads) as executor:
        packing_threads = [executor.submit(asynchronous_packer,
                                           sdk, sdks[sdk])
                           for sdk in sdks]
  
    output_file_name = os.path.join(target, 'plugins',
                                    'com.android.ide.eclipse.source_' +
                                    variables['VERSION'] + '.jar')
    icon_name = 'android_32x32.png'
    manifest = os.path.join('META-INF', 'MANIFEST.MF')
    assets = os.path.join(base, 'assets', 'plugins')
    with zipfile.ZipFile(output_file_name, 'w',
                         zipfile.ZIP_DEFLATED) as output:
        for item in ('about.html', 'about.ini', 'about.mappings',
                     icon_name):
            output.write(os.path.join(assets, item), item,
                         zipfile.ZIP_DEFLATED)
        output.writestr('about.properties',
                        preprocess(os.path.join(assets,
                                                'about.properties'),
                                   variables), zipfile.ZIP_DEFLATED)
        output.writestr(manifest,
                        preprocess(os.path.join(assets, manifest),
                                   variables),
                        zipfile.ZIP_DEFLATED)
        output.write(os.path.join(assets, icon_name),
                     os.path.join('icons', icon_name),
                     zipfile.ZIP_DEFLATED)

        concurrent.futures.wait(packing_threads)

        for sdk in sorted(sdks):
            logging.debug('Packing SDK %s', str(sdk))
            sources_zip = os.path.join(str(sdk), 'sources.zip')
            output.write(sdk_archives[sdk].name, sources_zip,
                         zipfile.ZIP_STORED)
            os.unlink(sdk_archives[sdk].name)

    return os.stat(output_file_name)[stat.ST_SIZE]
# }}}


def generate_artifacts(base, target, variables):  # {{{
    logging.info('Generating artifacts.jar')

    with zipfile.ZipFile(os.path.join(target, 'artifacts.jar'), 'w',
                         zipfile.ZIP_DEFLATED) as output:
        path = os.path.join(base, 'assets', 'artifacts.xml')
        output.writestr('artifacts.xml', preprocess(path, variables),
                        zipfile.ZIP_DEFLATED)
# }}}


def repack(directory, target_file):  # {{{
    logging.debug('Repacking plugin from %s to %s', directory, target_file)

    root_directory = os.path.abspath(directory)
    with zipfile.ZipFile(target_file, 'w', zipfile.ZIP_STORED) as output:
        for root, directories, files in os.walk(directory):
            for directory_name in directories:
                full_directory = os.path.join(root, directory_name)
                os.path.relpath(full_directory, root_directory)

            for file_name in files:
                source_file = os.path.join(root, file_name)
                target_file = os.path.relpath(source_file, root_directory)

                output.write(source_file, target_file, zipfile.ZIP_STORED)
# }}}


def main():  # {{{
    if ARGUMENTS.quiet:
        level = logging.CRITICAL
    elif ARGUMENTS.verbose is not None and ARGUMENTS.verbose == 1:
        level = logging.WARNING
    elif ARGUMENTS.verbose is not None and ARGUMENTS.verbose == 2:
        level = logging.INFO
    elif ARGUMENTS.verbose is not None and ARGUMENTS.verbose >= 3:
        level = logging.DEBUG
    else:
        level = logging.ERROR

    if not ARGUMENTS.threads:
        threads = multiprocessing.cpu_count()
    else:
        threads = ARGUMENTS.threads

    logging.basicConfig(format='%(levelname)s:%(message)s', level=level)

    VARS['VERSION'] = '%s.%s' % (ARGUMENTS.version[0],
                                 NOW.strftime('%Y%m%d%H%M%S'))

    sdks = collect_android_sources(ARGUMENTS.sdk_base[0])
    if not sdks:
        sys.exit(-1)

    if ARGUMENTS.zip:
        target = tempfile.mkdtemp()
    else:
        target = ARGUMENTS.target[0]
    create_target(target, ARGUMENTS.force)
    generate_site(ASSETS, target, VARS)
    generate_content(ASSETS, target, VARS)
    VARS['FEATURES_SIZE'] = generate_features(ASSETS, target, VARS)
    VARS['PLUGINS_SIZE'] = generate_plugins(ASSETS, target, VARS, sdks,
                                            threads)
    generate_artifacts(ASSETS, target, VARS)

    if ARGUMENTS.zip:
        if ARGUMENTS.force:
            os.unlink(ARGUMENTS.target[0])
        else:
            raise Exception('File already exists!')
        repack(target, ARGUMENTS.target[0])
        shutil.rmtree(target)

    logging.info('Plugin version %s generated in %s', VARS['VERSION'],
                 ARGUMENTS.target[0])
# }}}


if __name__ == '__main__':
    main()

# vim:sts=4:sw=4:et:syn=python:ff=unix:fdm=marker:number:

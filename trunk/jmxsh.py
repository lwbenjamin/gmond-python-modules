###  This script reports jmx metrics to ganglia.
###
###  Notes:
###    THIS IS AN UNTESTED VERSION!
###
###  Changelog:
###    v0.0.1 - 2010-07-29
###      * Initial version
###

###  Copyright Jamie Isaacs. 2010
###  License to use, modify, and distribute under the GPL
###  http://www.gnu.org/licenses/gpl.txt

import time
import subprocess
import traceback, sys
import tempfile
import logging

#logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(name)s - %(levelname)s\t Thread-%(thread)d - %(message)s", filename='/tmp/gmond.log', filemode='w')
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s\t Thread-%(thread)d - %(message)s", filename='/tmp/gmond.log2')
logging.debug('')
logging.debug('')
logging.debug('#################')
logging.debug('## starting up ##')
logging.debug('##################################################')

last_update = 0
stats = {}

METRICS = {}
HOST = 'localhost'
PORT = 8887
NAME = str(PORT)

MAX_UPDATE_TIME = 15
JMXSH = '/usr/share/java/jmxsh.jar'

def get_numeric(val):
	'''Try to return the numeric value of the string'''

	try:
		return int(val)
	except:
		pass

	try:
		return float(val)
	except:
		pass

	return val

def get_gmond_format(val):
	'''Return the formatting and value_type values to use with gmond'''
	tp = type(val).__name__

	if tp == 'int':
		return ('uint', '%u')
	elif tp == 'float':
		return ('float', '%.1f')
	elif tp == 'string':
		return ('string', '%u')
	else:
		return ('string', '%u')

def update_stats():
	logging.debug('updating stats')
	global last_update, stats
	
	cur_time = time.time()

	if cur_time - last_update < MAX_UPDATE_TIME:
		logging.debug(' wait ' + str(int(MAX_UPDATE_TIME - (cur_time - last_update))) + ' seconds')
		return True
	else:
		last_update = cur_time

	#####
	# Build jmxsh script into tmpfile
	sh  = '# jmxsh\njmx_connect -h ' + HOST + ' -p ' + PORT + '\n'
	for name,mbean in METRICS.items():
		sh += 'puts "' + name + ': [jmx_get -m ' + mbean + ']"\n'

	# Write to temp file
	(fd, fname) = tempfile.mkstemp()
	file = open(fname, 'w')
	file.write(sh)
	file.close()
	#logging.debug(fname + '\n' + sh)
	
	# run jmxsh.jar with the temp file as a script
	cmd = "java -jar " + JMXSH + " " + fname
	p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	out, err = p.communicate()
	logging.debug('cmd: ' + cmd + '\nout: ' + out + '\nerr: ' + err + '\ncode: ' + str(p.returncode))

	# we don't need the file anymore
	os.remove(fname)

	if p.returncode:
		logging.warning('failed executing ps\n' + cmd + '\n' + err)
		return False

	# now parse out the values
	for line in out.strip().split('\n'):
		params = line.split(': ')
		name = params[0]
		val = params[1]
		stats[name] = get_numeric(val)

	logging.debug('success refreshing stats')
	logging.debug('stats: ' + str(stats))

	return True

def get_stat(name):
	logging.debug('getting stat: ' + name)

	ret = update_stats()

	if ret:
		first = 'jmx_' + NAME + '_'
		if name.startswith(first):
			label = name[len(first):]
		else:
			label = name

		try:
			return stats[label]
		except:
			logging.warning('failed to fetch ' + name)
			return 0
	else:
		return 0

def metric_init(params):
	global descriptors
	global METRICS,HOST,PORT,NAME

	logging.debug('init: ' + str(params))

	try:
		HOST = params.pop('host')
		PORT = params.pop('port')
		NAME = params.pop('name')
		
	except:
		logging.warning('Incorrect parameters')

	METRICS = params

	update_stats()

	# dynamically build our descriptors based on the first run of update_stats()
	descriptions = dict()
	for name in stats:
		(value_type, format) = get_gmond_format(stats[name])
		descriptions[name] = {
			'value_type': value_type,
			'format': format
		}

	time_max = 60
	descriptors = []
	for label in descriptions:
		if stats.has_key(label):

			d = {
				'name': 'jmx_' + NAME + '_' + label,
				'call_back': get_stat,
				'time_max': time_max,
				'value_type': 'uint',
				'units': '',
				'slope': 'both',
				'format': '%u',
				'description': label,
				'groups': 'procstat'
			}

			# Apply metric customizations from descriptions
			d.update(descriptions[label])

			descriptors.append(d)

		else:
			logging.error("skipped " + label)

	#logging.debug('descriptors: ' + str(descriptors))

	return descriptors

def metric_cleanup():
	logging.shutdown()
	# pass

if __name__ == '__main__':
	from optparse import OptionParser
	import os

	logging.debug('running from cmd line')
	parser = OptionParser()
	parser.add_option('-p', '--param', dest='param', default='', help='module parameters')
	parser.add_option('-v', '--value', dest='value', default='', help='module values')
	parser.add_option('-b', '--gmetric-bin', dest='gmetric_bin', default='/usr/bin/gmetric', help='path to gmetric binary')
	parser.add_option('-c', '--gmond-conf', dest='gmond_conf', default='/etc/ganglia/gmond.conf', help='path to gmond.conf')
	parser.add_option('-g', '--gmetric', dest='gmetric', action='store_true', default=False, help='submit via gmetric')
	parser.add_option('-q', '--quiet', dest='quiet', action='store_true', default=False)
	parser.add_option('-t', '--test', dest='test', action='store_true', default=False, help='test the regex list')

	(options, args) = parser.parse_args()

	_param = options.param.split(',')
	_val = options.value.split('|')

	params = {}
	i = 0
	for name in _param:
		params[name] = _val[i]
		i += 1
	
	metric_init(params)

	if options.test:
		print('')
		print(' waiting ' + str(MAX_UPDATE_TIME) + ' seconds')
		time.sleep(MAX_UPDATE_TIME)
		update_stats()

	for d in descriptors:
		v = d['call_back'](d['name'])
		if not options.quiet:
			print ' %s: %s %s [%s]' % (d['name'], d['format'] % v, d['units'], d['description'])

		if options.gmetric:
			cmd = "%s --conf=%s --value='%s' --units='%s' --type='%s' --name='%s' --slope='%s'" % \
				(options.gmetric_bin, option.gmond_conf, v, d['units'], d['value_type'], d['name'], d['slope'])
			os.system(cmd)


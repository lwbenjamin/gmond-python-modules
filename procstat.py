###  This script reports process metrics to ganglia.
###
###  Notes:
###    This script exposes values for CPU and memory utilization
###    using the Linux command "ps" for user defined processes. You
###    can monitor single or multiple processes groups. This comes
###    in handy for monitoring services like Apache MPM prefork which
###    launches multiple child processes. Keep in mind that a well
###    formed regular expression is suggested to be used to limit the
###    possibility of a conflict from another service or command line
###    process.
###
###    This script also comes with the ability to test your regular
###    expressions via command line arguments.
###
###  Testing:
###    The following example is a good regular expression
###    to use to monitor Apache. It is a very specific and
###    direct expression: \/usr\/sbin\/httpd
###
###    $ python procstat.py -p httpd -r '\/usr\/sbin\/httpd' -t
###    Testing httpd: /\/usr\/sbin\/httpd/
###    CPU, MEM, PID, USER, ARGS
###     0.2  7956 17642 root     /usr/sbin/httpd
###     0.0  9380 17644 apache   /usr/sbin/httpd
###     0.2  9420 17645 apache   /usr/sbin/httpd
###     0.1  9404 17646 apache   /usr/sbin/httpd
###     0.3  9384 17647 apache   /usr/sbin/httpd
###     0.0  9400 17648 apache   /usr/sbin/httpd
###    Totals:
###    0.8 54944
###
###  Command Line:
###    $ python procstat.py -p httpd,opennms,splunk \
###    -r '\/usr\/sbin\/httpd','java.*Dopennms','splunkd.*start|twistd.*SplunkWeb'
###
###     procstat_httpd_mem: 194744 KB [The total memory utilization]
###     procstat_splunk_mem: 546912 KB [The total memory utilization]
###     procstat_opennms_mem: 608724 KB [The total memory utilization]
###     procstat_httpd_cpu: 0.0 percent [The total percent CPU utilization]
###     procstat_splunk_cpu: 0.9 percent [The total percent CPU utilization]
###     procstat_opennms_cpu: 7.1 percent [The total percent CPU utilization]
###
###  Example Regex:
###    httpd:   \/usr\/sbin\/httpd
###    mysqld:  \/usr\/libexec\/mysqld
###    splunk:  splunkd.*start|twistd.*SplunkWeb
###    opennms: java.*Dopennms
###    netflow: java.*NetFlow
###
###
###  Changelog:
###    v1.0.1 - 2010-07-23
###       * Initial version
###

###  Copyright Jamie Isaacs. 2010
###  License to use, modify, and distribute under the GPL
###  http://www.gnu.org/licenses/gpl.txt

import time
import subprocess
import traceback, sys
import logging

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s\t Thread-%(thread)d - %(message)s", filename='/tmp/procstat_log')
logging.debug('starting up')

last_update = 0
stats = {}

MAX_UPDATE_TIME = 15

PROCESSES = {}

def test(PROCESSES):
	logging.debug('testing processes and regex: ' + str(PROCESSES))
	
	for proc,regex in PROCESSES.items():
		print('Testing ' + proc + ': /' + regex + '/')
		print('CPU, MEM, PID, USER, ARGS')	

		awk_cmd = "ps -Ao pcpu,rss,pid,user,args | awk '/" + regex + "/ && !/awk/ && !/procstat\.py/ {_cpu+=$1; _rss+=$2; print $0} END {print \"Totals:\"; printf(\"%.1f %d\", _cpu,_rss)}'"
		p = subprocess.Popen(awk_cmd, shell=True, stdout=subprocess.PIPE)
		out, err = p.communicate()

		if p.returncode:
			print('failed getting stats')
			continue

		print(out)
		print('')

	logging.debug('success testing')

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
	# Update memory utilization
	try:
		i=0
		for proc,regex in PROCESSES.items():
			logging.debug(' updating cpu and mem usage for ' + proc)

			awk_cmd = "ps -Ao pcpu,rss,pid,user,args | awk '/" + regex + "/ && !/awk/ && !/procstat\.py/ {_cpu+=$1; _rss+=$2} END {printf(\"%.1f %d\", _cpu,_rss)}'"
			p = subprocess.Popen(awk_cmd, shell=True, stdout=subprocess.PIPE)
			out, err = p.communicate()
			logging.debug('  result: ' + out)

			if p.returncode:
				logging.warning('failed getting stats')
				continue

			vars = out.split()
			logging.debug('  vars: ' + str(vars))

			stats[proc + '_cpu'] = float(vars[0])
			stats[proc + '_mem'] = int(vars[1])


	except:
		logging.warning('error refreshing stats')
		logging.warning(traceback.format_exc())
		return False

	logging.debug('success refreshing stats')
	logging.debug('stats: ' + str(stats))

	return True

def get_stat(name):
	logging.debug('getting stat: ' + name)

	ret = update_stats()

	if ret:
		if name.startswith('procstat_'):
			label = name[9:]
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
	global PROCESSES

	logging.debug('init: ' + str(params))

	PROCESSES = params
		
	update_stats()

	descriptions = dict(
		cpu = {
			'units': 'percent',
			'value_type': 'float',
			'format': '%.1f',
			'description': 'The total percent CPU utilization'},

		mem = {
			'units': 'KB',
			'description': 'The total memory utilization'}
	)

	time_max = 60
	descriptors = []
	for label in descriptions:
		for proc in PROCESSES:
			if stats.has_key(proc + '_' + label):

				d = {
					'name': 'procstat_' + proc + '_' + label,
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
				logging.warning("skipped " + proc + '_' + label)

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
	parser.add_option('-p', '--processes', dest='processes', default='', help='processes to explicitly check')
	parser.add_option('-r', '--regex', dest='regex', default='', help='regex for each processes')
	parser.add_option('-b', '--gmetric-bin', dest='gmetric_bin', default='/usr/bin/gmetric', help='path to gmetric binary')
	parser.add_option('-c', '--gmond-conf', dest='gmond_conf', default='/etc/ganglia/gmond.conf', help='path to gmond.conf')
	parser.add_option('-g', '--gmetric', dest='gmetric', action='store_true', default=False, help='submit via gmetric')
	parser.add_option('-q', '--quiet', dest='quiet', action='store_true', default=False)
	parser.add_option('-t', '--test', dest='test', action='store_true', default=False, help='test the regex list')

	(options, args) = parser.parse_args()

	_procs = options.processes.split(',')
	_regex = options.regex.split(',')
	params = {}
	i = 0
	for proc in _procs:
		params[proc] = _regex[i]
		i += 1
	
	if options.test:
		test(params)
		sys.exit(0)

	metric_init(params)

	for d in descriptors:
		v = d['call_back'](d['name'])
		if not options.quiet:
			print ' %s: %s %s [%s]' % (d['name'], v, d['units'], d['description'])

		if options.gmetric:
			cmd = "%s --conf=%s --value='%s' --units='%s' --type='%s' --name='%s' --slope='%s'" % \
				(options.gmetric_bin, option.gmond_conf, v, d['units'], d['value_type'], d['name'], d['slope'])
			os.system(cmd)


#!/usr/bin/env python2.7
# pylint: disable-msg=C0103, C0111
import sys
import os
import glob
import json
import datetime
import time
import numpy as np
from multiprocessing import Pool
from time import mktime

SECS_PER_HOUR = 3600

#Returns set containing all given file type with the extension removed.
def get_file_names(path = './', ext = 'txt'):
    return {os.path.splitext(os.path.basename(f))[0] for f in glob.glob(path + '*' + ext)}

#Write tab-separated line to file out, with first element followed by list.
def write_ts_line(f_out, vals):
    f_out.write('\t'.join([str(val) for val in vals]) + '\n')

# Given an array of perc of resource used, returns
# 0 - all resources are used < 10%
# 1 - at least one resource is used >10% and <50%
# 2 - at least one resource is used >50% and <80%
# 3 - at least one resource is used >80%
# 4 - all resources are used >50%
# 5 - all resources are used >80%
def get_overall_class(resources):
    if all([r > 0.8 for r in resources]):
        return 5
    if all([r > 0.5 for r in resources]):
        return 4
    if any([r > 0.8 for r in resources]):
        return 3
    if any([r > 0.5 for r in resources]):
        return 2
    if any([r > 0.1 for r in resources]):
        return 1
    return 0

def gen_tsv(path_file_args):
    yperf_path, txt_file_name = path_file_args
    print('About to generate tsv for ' + txt_file_name)
    with open(yperf_path + 'raw/' + txt_file_name + '.txt') as f_in, \
            open(yperf_path + 'tsv/' + txt_file_name + '.tsv', 'w') as f_out:
        AGG_MEASURES = [{
                'num': ['nr', 'nw'],
                'op': max,
                'den': 100.0e6,
                'name': 'network'
            }, {
                'num': ['dr', 'dw'],
                'op': sum,
                'den': 150.0e6,
                'name': 'disk'
            }, {
                'num': ['cu', 'cs'],
                'op': sum,
                'den': 3200.0,
                'name': 'cpu'
            }]
        raw_smooth = ['nr', 'nw']
        prev_json_perf = None
        raw_names = ['nr', 'nw', 'dr', 'dw', 'cu', 'cs', 'ci', 'cn', 'cw']
        prev_epoch = None
        n_lines = 3600
        for line in f_in:
            epoch, perf_vals = line.split('\t')
            epoch = int(epoch)
            if (epoch <= prev_epoch):
                continue # TODO print warning.
            json_perf = json.loads(perf_vals)
            if prev_epoch is None:
                raw_names = raw_names + [measure for measure in json_perf if measure not in raw_names]
                aggs = [agg['name'] for agg in AGG_MEASURES]
                headers = ['epoch', 'class', 'max', 'mean'] + aggs + raw_names
                write_ts_line(f_out, headers)
                prev_epoch = epoch - 1
                if epoch % SECS_PER_HOUR != 0:
                    print('* Warning * {0} did not start aligned at {1}, first epoch was {2}.'.format(txt_file_name, SECS_PER_HOUR, epoch))
                    prev_epoch = (epoch // SECS_PER_HOUR) * SECS_PER_HOUR - 1 # To add correct number of nan values.
            # Will usually never do this, but if any epochs have been skipped, then generate nan values.
            for i in range(epoch - prev_epoch - 1):
                n_lines -= 1
                write_ts_line(f_out, [str(prev_epoch + i + 1)] + ['nan' for i in range(len(headers) - 1)])
            # Store raw values, but for network use moving average of 2 because it seems to only record every 2 seconds on iln.
            raw_json_perf = json_perf
            json_perf = {k: (v + prev_json_perf[k]) / 2.0 if k in raw_smooth and prev_json_perf else v for k, v in json_perf.items()}
            raw_vals = [json_perf[name] for name in raw_names]
            agg_vals = [agg['op']((json_perf[meas] for meas in agg['num'])) / agg['den'] for agg in AGG_MEASURES]
            n_lines -= 1
            write_ts_line(f_out, [epoch, get_overall_class(agg_vals), max(agg_vals), sum(agg_vals) / float(len(agg_vals))] + agg_vals + raw_vals)
            prev_epoch = epoch
            prev_json_perf = raw_json_perf
        if (n_lines < 0 or n_lines > 100):
            print('* Warning * n_lines is {0} instead of 0.', n_lines)
        for i in range(n_lines):
            write_ts_line(f_out, [str(prev_epoch + i + 1)] + ['nan' for i in range(len(headers) - 1)])

        print('Generated tsv for ' + txt_file_name)

def dump_json(json_data, f_name):
    """Writes json to file name using space-efficient sperators.
    """
    with open(f_name, 'w') as f:
        json.dump(json_data, f, separators=(',',':'))

def gen_json(arr, folder, file_name, reset):
    file_name = folder + file_name + '.gr.json'
    if not reset and os.path.isfile(file_name):
        return
    MILLI_PER_SECOND = 1000
    if (arr['epoch'].size % SECS_PER_HOUR != 0):
        print('* Warning * array has {0} rows.'.format(arr['epoch'].size))
    data = []
    for name in arr.dtype.names:
        if name == 'epoch':
            continue
        data.append({'name': name,
            'data': [None if np.isnan(val) else val for val in arr[name]],
            'pointStart': arr['epoch'][0] * MILLI_PER_SECOND,
            'pointInterval': MILLI_PER_SECOND})
    res = {'epoch_start': arr['epoch'][0], 'length': arr['epoch'].size, 'series': data}
    dump_json(res, file_name)

def gen_json_series(path_file_args):
    yperf_path, file_name = path_file_args
    arr = get_np_tsv(yperf_path, file_name)
    print('About to generate raw json for ' + file_name)
    gen_json(arr, yperf_path, file_name)
    print('Generated raw json for {0}.'.format(file_name))

def get_np_tsv(path, name):
    return np.genfromtxt(path + 'tsv/' + name + '.tsv', names = True)

# For each col, whenever there are missing values, they first non-nan value
# should get evenly distributed among itself and the missing values.
def remove_nan(arr):
    for name in arr.dtype.names:
        col = arr[name]
        prevNanInd = None
        for i in xrange(col.size):
            if prevNanInd is None and np.isnan(col[i]):
                prevNanInd = i
            elif prevNanInd is not None and not np.isnan(col[i]):
                for j in xrange(prevNanInd, i + 1):
                    col[j] = col[i] / (i - prevNanInd + 1)
                prevNanInd = None
    return arr

def gen_entire_arr(files, path):
    for i, f in enumerate(files):
        a = get_np_tsv(path, f)
        if i == 0: #TODO more elegant?
            arr = a
        else:
            arr = np.hstack((arr, a))
    remove_nan(arr)
    return arr;

def process_tsv(yperf_path, reset):
    txt_files = get_file_names(yperf_path + 'raw/', 'txt')
    tsv_files = get_file_names(yperf_path + 'tsv/', 'tsv')
    new_files = list(txt_files) if reset else [f for f in txt_files if f not in tsv_files]
    process_files(new_files, gen_tsv, yperf_path)

def process_files(file_names, fn_to_apply, path):
    N_THREADS = 4
    if len(file_names) == 1:
        fn_to_apply([path, file_names[0]])
    elif len(file_names) > 1:
        p = Pool(4)
        p.map(fn_to_apply, ([path, f] for f in file_names))
    else:
        print(' *WARNING* No new files exist for path "{0}" to apply "{1}"'.format(path, fn_to_apply.__name__))

def process_json_series(yperf_path):
    tsv_files = get_file_names(yperf_path + 'tsv/', 'tsv')
    json_files = get_file_names(yperf_path + 'json_series/', 'json')
    new_files = [f for f in tsv_files if f not in json_files]
    process_files(new_files, gen_json_series, yperf_path)

def get_yperf_name(tm):
    """ Returns the file prefix that would correspond to a certain struct
    datetime t. """
    return 'yperf-' + tm.strftime('%Y%m%d-%H')

def get_file_list(times):
    file_list = []
    curr = times[0]
    end = times[-1]
    while curr < end:
        file_list.append(get_yperf_name(curr))
        curr += datetime.timedelta(hours = 1)
    last = get_yperf_name(end)
    if file_list[-1] != last:
        file_list.append(last)
    return file_list

def create_agg_tables(sum_arr, n_hosts, step_times, agg_col_names, json_path, reset):
    sum_f_name = json_path + 'sum.tb.json'
    avg_f_name = json_path + 'avg.tb.json'

    #temp hack from stackoverflow
    from json import encoder
    orig_float_repr = encoder.FLOAT_REPR
    encoder.FLOAT_REPR = lambda o: format(o, '.2f')

    if not reset and os.path.isfile(sum_f_name) and os.path.isfile(avg_f_name):
        print(' *WARNING* Table files already exist, returning.')
        return
    step_epochs = [int(time.mktime(t.timetuple())) for t in step_times]
    start_epoch = step_epochs[0]
    start_index = np.where(sum_arr['epoch'] == start_epoch)[0]
    prev_epoch = None
    sum_rows = []
    agg_names = [name for name in sum_arr.dtype.names if name != 'epoch']
    for i, epoch in enumerate(step_epochs):
        if prev_epoch is not None:
            secs_elapsed = epoch - prev_epoch
            row = [i - 1, secs_elapsed]
            for name in agg_col_names:
                start_i = prev_epoch - start_epoch + start_index
                end_i = epoch - start_epoch + start_index
                row.append(sum_arr[name][start_i:end_i].sum())
            sum_rows.append(row)
        prev_epoch = epoch
    header_row = ['step', 'time'] + agg_names
    sum_row = ['sum'] + [x for x in np.array(sum_rows).sum(axis = 0)][1:]
    sum_rows.append(sum_row)
    sum_res = {'aaData': sum_rows, 'aoColumns': [{'sTitle': x, 'sType': 'numeric'} for x in header_row]}
    dump_json(sum_res, sum_f_name)

    avg_rows = [row[0:2] + [x for x in np.array(row[2:]) / (row[1] * n_hosts)] for row in sum_rows]
    avg_res = sum_res
    avg_res['aaData'] = avg_rows
    dump_json(avg_res, avg_f_name)

    #TODO find another way
    encoder.FLOAT_REPR = orig_float_repr

# Copies needed HTML/JS files (assumes json already there), then copies entire thing to WWW
def deploy_to_WWW(run_name, deploy_src_fold):
    os.system('cp -r deploy_starter/* ' + deploy_src_fold)
    command = ('rsync -avW -e "ssh -i '
            '/lfs/iln01/0/snapworld_key/id_rsa" {0} '
            'snapworld@snap.stanford.edu:/lfs/snap/0/snapworld/metrics/{1}')\
                    .format(deploy_src_fold, run_name) #TODO Do not hard code iln01 or snap.
    os.system(command)
    print('Now you can view run metrics at http://snapworld.stanford.edu/metrics/{0}/'.format(run_name))

def get_run_info(master_log_name):
    with open(master_log_name) as f:
        line = f.readline()
        return json.loads(
            line[line.find('{'):]
                .replace("'", '"')
                .replace('True', 'true')
                .replace('False', 'false')
        )

def get_times(times):
    return [mktime(t.timetuple()) for t in times]

def gen_report(report_specs, reset):
    times = [datetime.datetime.fromtimestamp(t) for t in
            report_specs['step_times']]
    run_info = report_specs['meta_data']
    files = get_file_list(times)
    run_name = report_specs['run_name']
    yp_path = 'reports/' + run_name
    deploy_path = yp_path + '/deploy/'
    json_path = deploy_path + '/json/'
    os.system('mkdir -p ' + json_path)
    sum_arr = None
    for supervisor in run_info['hosts']:
        path = yp_path + '/data/' + supervisor['id'] + '/'
        os.system('mkdir -p ' + path + '{tsv,raw}/')
        ip_addr = supervisor['host']
        file_list = ''
        for f in files:
            if reset or not os.path.isfile(path + 'raw/' + f + '.txt'):
                file_list += '{0}@{1}:/var/yperf/{2}.txt '.format(os.environ['USER'], ip_addr, f)
        if file_list:
            command = 'scp {0} {1}raw/'.format(file_list, path)
            print('Copying over yperf files using \n{0}'.format(command)) # WODO remove.
            os.system(command)
        process_tsv(path, reset)
        try:
            arr = gen_entire_arr(files, path) #TODO naming
        except:
            print(' *WARNING* Could not locate yperf/tsv from {0}, skipping'.format(ip_addr))
            continue
        if sum_arr is None:
            sum_arr = arr.copy()
            max_arr = arr.copy()
            orig_epoch = arr['epoch']
            to_agg = [col_name for col_name in arr.dtype.names if col_name != 'epoch']
        else:
            if not np.all(arr['epoch'] == orig_epoch):
                print(' *ERROR* - epochs for {0} do not match original.'.format(supervisor['id']))
            for col in to_agg:
                sum_arr[col] = sum_arr[col] + arr[col]
                max_arr[col] = np.maximum(max_arr[col], arr[col])
        gen_json(arr, json_path, supervisor['id'], reset)
    avg_arr = sum_arr.copy()
    n_hosts = len(run_info['hosts'])
    for col in to_agg:
        avg_arr[col] = sum_arr[col] / float(n_hosts)
    gen_json(avg_arr, json_path, 'avg', reset)
    gen_json(max_arr, json_path, 'max', reset)
    create_agg_tables(sum_arr, n_hosts, times, to_agg, json_path, reset)
    ind_json = {}
    ind_json['step_times'] = get_times(times)
    ind_json['run_info'] = run_info
    agg_tables = [{'title': 'Average Table', 'file': 'avg.tb.json', 'type': 'table', 'load': True},
                  {'title': 'Sums Table', 'file': 'sum.tb.json', 'type': 'table', 'load': True}]
    agg_graphs = [{'title': 'Mean Graph', 'file': 'avg.gr.json', 'type': 'graph', 'load': True},
                  {'title': 'Max Graph', 'file': 'max.gr.json', 'type': 'graph', 'load': False}]
    supervisor_graphs = [
            {
                'title': 'Supervisor {} Graph (IP: {})'.format(supervisor['id'], supervisor['host']),
                'file': supervisor['id'] + '.gr.json',
                'type': 'graph',
                'load': False
            }
            for supervisor in run_info['hosts']]
    ind_json['views'] = agg_tables + agg_graphs + supervisor_graphs
    dump_json(ind_json, json_path + 'index.json')
    deploy_to_WWW(run_name, deploy_path)

def read_json(input_file):
    """Will either load json data in file named input_file or load from
    stdin"""
    if input_file is not None:
        with open(input_file, 'w') as fil:
            return json.load(fil)
    return json.load(sys.stdin)

if __name__ == '__main__':
    import argparse
    os.chdir(os.path.dirname(sys.argv[0]))
    os.system('mkdir -p reports')
    parser = argparse.ArgumentParser()
    parser.add_argument('input_file', nargs='?')
    parser.add_argument('-r', '--reset', action = 'store_true')
    args = parser.parse_args()
    gen_report(read_json(args.input_file), args.reset)

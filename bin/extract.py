#!/usr/bin/env python

import argparse
import gzip
import itertools
import json
import logging
import os
import re
import sys

import pyfastx

logger = logging.getLogger(__name__)



def openfile(file_name, mode='rt', **kwargs):
    """open gzip or plain file"""
    if file_name.endswith('.gz'):
        file_obj = gzip.open(file_name, mode=mode, **kwargs)
    else:
        file_obj = open(file_name, mode=mode, **kwargs)
    return file_obj

def get_seq_str(seq, sub_pattern):
    """
    join seq slices.

    Args:
        seq: usually R1 read
        sub_pattern: [slice(0,8),slice(16,24)]

    Returns:
        joined intervals seq

    >>> sub_pattern_dict = [slice(0,2)]
    >>> seq = "A" * 2 + "T" * 2
    >>> get_seq_str(seq, sub_pattern_dict)
    'AA'
    """
    return "".join([seq[x] for x in sub_pattern])


def findall_mismatch(seq, n_mismatch=1, bases='ACGTN'):
    """
    choose locations where there's going to be a mismatch using combinations
    and then construct all satisfying lists using product

    Return:
    all mismatch <= n_mismatch set.

    >>> answer = set(["TCG", "AAG", "ACC", "ATG", "ACT", "ACN", "GCG", "ANG", "ACA", "ACG", "CCG", "AGG", "NCG"])
    >>> seq_set = findall_mismatch("ACG")
    >>> seq_set == answer
    True
    """
    seq_set = set()
    seq_len = len(seq)
    if n_mismatch > seq_len:
        n_mismatch = seq_len
    for locs in itertools.combinations(range(seq_len), n_mismatch):
        seq_locs = [[base] for base in seq]
        for loc in locs:
            seq_locs[loc] = list(bases)
        for poss in itertools.product(*seq_locs):
            seq_set.add(''.join(poss))
    return seq_set

def get_mismatch_dict(seq_list, n_mismatch=1):
    """
    Return:
    mismatch dict. Key: mismatch seq, value: seq in seq_list

    >>> seq_list = ["AACGTGAT", "AAACATCG"]
    >>> mismatch_dict = get_mismatch_dict(seq_list)
    >>> mismatch_dict["AACGTGAA"] == "AACGTGAT"
    True
    """
    mismatch_dict = {}
    for seq in seq_list:
        seq = seq.strip()
        if seq == '':
            continue
        for mismatch_seq in findall_mismatch(seq, n_mismatch):
            mismatch_dict[mismatch_seq] = seq
    return mismatch_dict


def read_one_col(fn):
    """read one column file into list"""
    with open(fn) as f:
        return [x.strip() for x in f]


def parse_pattern(pattern, allowed="CLUNT"):
    """
    >>> pattern_dict = parse_pattern("C8L16C8L16C8L1U12T18")
    >>> pattern_dict['C']
    [slice(0, 8, None), slice(24, 32, None), slice(48, 56, None)]
    >>> pattern_dict['L']
    [slice(8, 24, None), slice(32, 48, None), slice(56, 57, None)]
    """
    pattern_dict = {}
    p = re.compile(r'([A-Z])(\d+)')
    tmp = p.findall(pattern)
    if not tmp:
        sys.exit(f'Invalid pattern: {pattern}')
    start = 0
    for x, length in tmp:
        if x not in allowed:
            sys.exit(f'Invalid pattern: {pattern}')
        if x not in pattern_dict:
            pattern_dict[x] = []
        end = start + int(length)
        pattern_dict[x].append(slice(start,end))
        start = end
    return pattern_dict


def get_raw_mismatch(files: list, n_mismatch: int):
    """
    Args:
        files: whitelist file paths
        n_mismatch: allowed number of mismatch bases
    Returns:
        raw_list
        mismatch_list
    """    
    raw_list, mismatch_list = [], []
    for f in files:
        barcodes = read_one_col(f)
        raw_list.append(set(barcodes))
        barcode_mismatch_dict = get_mismatch_dict(barcodes, n_mismatch)
        mismatch_list.append(barcode_mismatch_dict)

    return raw_list, mismatch_list


def check_seq_mismatch(seq_list, raw_list, mismatch_list):
    '''
    Returns
        valid: True if seq in mismatch_list
        corrected: True if seq in mismatch_list but not in raw_list
        res: joined seq

    >>> seq_list = ['ATA', 'AAT', 'ATA']
    >>> correct_set_list = [{'AAA'},{'AAA'},{'AAA'}]
    >>> mismatch_dict_list = [get_mismatch_dict(['AAA'])] * 3

    >>> check_seq_mismatch(seq_list, correct_set_list, mismatch_dict_list)
    (True, True, 'AAA_AAA_AAA')

    >>> seq_list = ['AAA', 'AAA', 'AAA']
    >>> check_seq_mismatch(seq_list, correct_set_list, mismatch_dict_list)
    (True, False, 'AAA_AAA_AAA')
    '''
    valid = True
    corrected = False
    res = []
    for index, seq in enumerate(seq_list):
        if seq not in raw_list[index]:
            if seq not in mismatch_list[index]:
                valid = False
                res = []
            else:
                corrected = True
                res.append(mismatch_list[index][seq])
        else:
            res.append(seq)

    return valid, corrected, '_'.join(res)

def get_protocol_dict(assets_dir):
    """
    Return:
    protocol_dict. Key: protocol name, value: protocol dict

    >>> protocol_dict = get_protocol_dict("./assets/")
    >>> protocol_dict["GEXSCOPE-MicroBead"]["pattern_dict"]
    {'C': [slice(0, 12, None)], 'U': [slice(12, 20, None)]}
    """
    json_file = os.path.join(assets_dir, "protocols.json")
    protocol_dict = json.load(open(json_file))
    whitelist_dir = os.path.join(assets_dir, "whitelist")
    # add folder prefix
    for protocol in protocol_dict:
        cur = protocol_dict[protocol]
        bc = cur.get("bc", [])
        linker = cur.get("linker", [])
        if bc:
            cur["bc"] = [os.path.join(whitelist_dir, protocol, x) for x in bc]
        if linker:
            cur["linker"] = [os.path.join(whitelist_dir, protocol, x) for x in linker]
        cur["pattern_dict"] = parse_pattern(cur["pattern"])
    return protocol_dict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample', required=True)
    parser.add_argument('--fq1', required=True)
    parser.add_argument('--fq2', required=True)
    parser.add_argument('--fq3', required=True)
    parser.add_argument('--assets_dir', required=True)
    parser.add_argument('--protocol', required=True)
    args = parser.parse_args()
    # protocol
    protocol_dict = get_protocol_dict(args.assets_dir)
    protocol = protocol_dict[args.protocol]
    pattern_dict = protocol["pattern_dict"]
    raw_list,  mismatch_list = get_raw_mismatch(protocol["bc"], 1)

    # out_fq
    out_fq_fn = {x: f"{args.sample}_R{x}.fq.gz" for x in [1,3]}
    outdict = {k:openfile(v,'wt') for k,v in out_fq_fn.items()}

    fq1_list = args.fq1.split(',')
    fq2_list = args.fq2.split(',')
    fq3_list = args.fq3.split(',')
    n = 0
    for fq1,fq2,fq3 in zip(fq1_list, fq2_list, fq3_list):
        fq1 = pyfastx.Fastx(fq1)
        fq2 = pyfastx.Fastx(fq2)
        fq3 = pyfastx.Fastx(fq3)

        for (name1, seq1, qual1), (name2,seq2,qual2), (name3, seq3, qual3) in zip(fq1, fq2, fq3):
            n += 1
            bc_list = [seq2[x] for x in pattern_dict["C"]]
            valid, corrected, corrected_seq = check_seq_mismatch(bc_list, raw_list, mismatch_list)
            if valid:
                read_name = f"{corrected_seq}:{n}"
                outdict[1].write(f"@{read_name}\n{seq1}\n+\n{qual1}\n")
                outdict[3].write(f"@{read_name}\n{seq3}\n+\n{qual3}\n")

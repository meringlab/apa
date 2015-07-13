import pysam
import apa
import os
import pybio
import time
import glob
import sys

PAS_hexamers = [
    'AATAAA',
    'ATTAAA',
    'AGTAAA',
    'TATAAA',
    'CATAAA',
    'GATAAA',
    'AATATA',
    'AATACA',
    'AATAGA',
    'ACTAAA',
    'AAGAAA',
    'AATGAA'
]

def match_pas(seq):
    for hexamer in PAS_hexamers:
        if seq.find(hexamer)!=-1:
            return True
    return False

def write_bed(data, filename):
    # write bed file from dictionary data {chr:strand}{position:value}
    # http://www.cgat.org/~andreas/documentation/pysam/api.html
    # Coordinates in pysam are always 0-based (following the python convention). SAM text files use 1-based coordinates.
    f = open(filename, "wt")
    for chr_strand, pos_data in data.items():
        chr, strand = chr_strand.split(":")
        positions = [(pos, len(rnd_set)) for pos, rnd_set in pos_data.items()]
        positions.sort()
        for pos, cDNA in positions:
            if strand=="+":
                f.write("%s\t%s\t%s\t%s\n" % (chr, pos, pos+1, cDNA))
            else:
                f.write("%s\t%s\t%s\t-%s\n" % (chr, pos, pos+1, cDNA))
    f.close()

#def bed_raw(lib_id, map_id=1, force=False):
#    lib = apa.annotation.libs[lib_id]
#    for exp_id, exp_data in lib.experiments.items():
#        if type(apa.config.process)==list and exp_data["map_to"] not in apa.config.process:
#            continue
#        if exp_data["method"]=="pAseq":
#            apa.bed.bed_raw_paseq(lib_id, exp_id=exp_id, map_id=1, force=force)
#        if exp_data["method"]=="paseqx":
#            apa.bed.bed_raw_paseqx(lib_id, exp_id=exp_id, map_id=1, force=force)

def bed_raw(lib_id, exp_id, map_id=1, force=False):
    lib = apa.annotation.libs[lib_id]
    exp_data = lib.experiments[exp_id]
    # skip species we don't process (see apa.config)
    if type(apa.config.process)==list and exp_data["map_to"] not in apa.config.process:
        return
    if exp_data["method"]=="pAseq":
        apa.bed.bed_raw_paseq(lib_id, exp_id, map_id=1, force=force)
    if exp_data["method"]=="paseqx":
        apa.bed.bed_raw_paseqx(lib_id, exp_id, map_id=1, force=force)

def bed_raw_paseq(lib_id, exp_id, map_id, force=False):
    assert(apa.annotation.libs[lib_id].experiments[exp_id]["method"]=="pAseq")
    # http://www.cgat.org/~andreas/documentation/pysam/api.html
    # Coordinates in pysam are always 0-based (following the python convention). SAM text files use 1-based coordinates.

    r_filename = apa.path.r_filename(lib_id, exp_id)
    t_filename = apa.path.t_filename(lib_id, exp_id)

    # don't redo analysis if files exists
    if (os.path.exists(r_filename) and not force) or (os.path.exists(t_filename) and not force):
        print "%s_e%s_m%s : R/T BED : already processed or currently processing" % (lib_id, exp_id, map_id)
        return

    lib = apa.annotation.libs[lib_id]
    exp_data = lib.experiments[exp_id]
    if type(apa.config.process)==list and exp_data["map_to"] not in apa.config.process:
        return

    open(r_filename, "wt").close()
    open(t_filename, "wt").close()

    dataR = {}
    dataT = {}
    genome = apa.annotation.libs[lib_id].experiments[exp_id]["map_to"]
    bam_filename = os.path.join(apa.path.data_folder, lib_id, "e%s" % exp_id, "m%s" % map_id, "%s_e%s_m%s.bam" % (lib_id, exp_id, map_id))
    bam_file = pysam.Samfile(bam_filename)
    a_number = 0
    pas_count = 0
    for a in bam_file.fetch():
        a_number += 1

        if a_number%10000==0:
            print "%s_e%s_m%s : %sK reads processed : %s (pas count = %s)" % (lib_id, exp_id, map_id, a_number/1000, bam_filename, pas_count)

        # do not process spliced reads
        cigar = a.cigar
        cigar_types = [t for (t, v) in cigar]
        if 3 in cigar_types:
            continue

        read_id = int(a.qname)
        chr = bam_file.getrname(a.tid)
        strand = "+" if not a.is_reverse else "-"
        # we use the reference positions of the aligned read (aend, pos)
        # relative positions are stored in qend, qstart
        if strand=="+":
            pos_end = a.aend - 1 # aend points to one past the last aligned residue, also see a.positions
            assert(pos_end==a.positions[-1])
        else:
            pos_end = a.pos
            assert(pos_end==a.positions[0])
        rnd_code = apa.annotation.rndcode(lib_id, read_id)

        aremoved = 0
        if a.is_reverse:
            last_cigar = a.cigar[0]
        else:
            last_cigar = a.cigar[-1]
        if last_cigar[0]==4:
            aremoved = last_cigar[1]

        key = "%s:%s" % (chr, strand)

        # update T file
        if aremoved>=6:
            true_site = True
            if strand=="+":
                downstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end+1, pos_end+15)
                upstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end-36, pos_end-1)
                #aligned_seq = a.query
            else:
                downstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end-15, pos_end-1) # if strand=-, already returns RC
                upstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end+1, pos_end+36) # if strand=-, already returns RC
                #aligned_seq = pybio.sequence.reverse_complement(a.query)

            if match_pas(upstream_seq):
                true_site = True
                pas_count += 1

            if downstream_seq.startswith("AAAA") or downstream_seq[:10].count("A")>=5 or upstream_seq.endswith("AAAA") \
                or upstream_seq[-10:].count("A")>=5:
                true_site = False

            if true_site:
                temp = dataT.get(key, {})
                temp2 = temp.get(pos_end, set())
                temp2.add(rnd_code)
                temp[pos_end] = temp2
                dataT[key] = temp

        # update R file
        temp = dataR.get(key, {})
        temp2 = temp.get(pos_end, set())
        temp2.add(rnd_code)
        temp[pos_end] = temp2
        dataR[key] = temp

    # write R file
    write_bed(dataR, r_filename)
    # write T file
    write_bed(dataT, t_filename)

def bed_raw_paseqx(lib_id, exp_id, map_id, force=False):
    assert(apa.annotation.libs[lib_id].experiments[exp_id]["method"]=="paseqx")
    # http://www.cgat.org/~andreas/documentation/pysam/api.html
    # Coordinates in pysam are always 0-based (following the python convention). SAM text files use 1-based coordinates.

    r_filename = apa.path.r_filename(lib_id, exp_id)
    t_filename = apa.path.t_filename(lib_id, exp_id)

    # don't redo analysis if files exists
    if (os.path.exists(r_filename) and not force) or (os.path.exists(t_filename) and not force):
        print "%s_e%s_m%s : R/T BED : already processed or currently processing" % (lib_id, exp_id, map_id)
        return

    lib = apa.annotation.libs[lib_id]
    exp_data = lib.experiments[exp_id]
    if type(apa.config.process)==list and exp_data["map_to"] not in apa.config.process:
        return

    open(r_filename, "wt").close()
    open(t_filename, "wt").close()

    dataR = {}
    dataT = {}
    genome = apa.annotation.libs[lib_id].experiments[exp_id]["map_to"]
    bam_filename = os.path.join(apa.path.data_folder, lib_id, "e%s" % exp_id, "m%s" % map_id, "%s_e%s_m%s.bam" % (lib_id, exp_id, map_id))
    bam_file = pysam.Samfile(bam_filename)
    a_number = 0
    for a in bam_file.fetch():
        a_number += 1

        if a_number%10000==0:
            print "%s_e%s_m%s : %sK reads processed : %s" % (lib_id, exp_id, map_id, a_number/1000, bam_filename)

        cigar = a.cigar
        cigar_types = [t for (t, v) in cigar]
        if 3 in cigar_types: # skip spliced reads
            continue

        aremoved = 0
        if a.is_reverse:
            last_cigar = a.cigar[-1]
        else:
            last_cigar = a.cigar[0]
        if last_cigar[0]==4:
            aremoved = last_cigar[1]

        read_id = a.qname
        chr = bam_file.getrname(a.tid)
        strand = "+" if not a.is_reverse else "-"
        # we use the reference positions of the aligned read (aend, pos)
        # relative positions are stored in qend, qstart
        if strand=="+":
            pos_end = a.positions[0]
        else:
            pos_end = a.positions[-1]
        # for paseqx, we turn strand
        strand = {"+":"-", "-":"+"}[strand]

        key = "%s:%s" % (chr, strand)

        # update T file
        true_site = True
        if strand=="+":
            downstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end+1, pos_end+15)
            upstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end-36, pos_end-1)
        else:
            # if strand=-, already returns RC
            downstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end-15, pos_end-1)
            upstream_seq = pybio.genomes.seq(genome, chr, strand, pos_end+1, pos_end+36)

        if match_pas(upstream_seq):
            true_site = True

        if downstream_seq.startswith("AAAAA") or downstream_seq[:10].count("A")>=6:   #or upstream_seq.endswith("AAAA") or upstream_seq[-10:].count("A")>=5:
            true_site = False

        if true_site:
            temp = dataT.get(key, {})
            temp2 = temp.get(pos_end, set())
            temp2.add(read_id)
            temp[pos_end] = temp2
            dataT[key] = temp

        # update R file
        temp = dataR.get(key, {})
        temp2 = temp.get(pos_end, set())
        temp2.add(read_id)
        temp[pos_end] = temp2
        dataR[key] = temp

    # write R file
    write_bed(dataR, r_filename)
    # write T file
    write_bed(dataT, t_filename)

def bed_expression(lib_id, exp_id, map_id=1, force=False, polyid=None):
    exp_id = int(exp_id)
    exp_data = apa.annotation.libs[lib_id].experiments[exp_id]
    map_to = exp_data["map_to"]
    if exp_data["method"]=="pAseq":
        apa.bed.bed_expression_paseq(lib_id, exp_id=exp_id, map_id=1, map_to=map_to, force=force)
    if exp_data["method"]=="paseqx":
        apa.bed.bed_expression_paseqx(lib_id, exp_id=exp_id, map_id=1, map_to=map_to, polyid=polyid, force=force)

def bed_expression_paseq(lib_id, exp_id, map_id, map_to, force=False):
    genome = apa.annotation.libs[lib_id].experiments[exp_id]["map_to"]
    r_filename = apa.path.r_filename(lib_id, exp_id)
    e_filename = apa.path.e_filename(lib_id, exp_id)
    e_filename_ucsc = apa.path.e_filename(lib_id, exp_id, filetype="ucsc")
    polyadb_filename = apa.path.polyadb_filename(genome)

    if type(apa.config.process)==list and map_to not in apa.config.process:
        return

    if os.path.exists(e_filename) and not force:
        print "%s_e%s_m%s : E BED : already processed or currently processing" % (lib_id, exp_id, map_id)
    else:
        print "%s_e%s_m%s : E BED file : start" % (lib_id, exp_id, map_id)
        open(e_filename, "wt").close() # touch E BED (processing)
        e = pybio.data.Bedgraph()
        e.overlay(polyadb_filename, r_filename, region_up=100, region_down=25)
        e.save(e_filename)

    if os.path.exists(e_filename_ucsc) and not force:
        print "%s_e%s_m%s_ucsc : E BED : already processed or currently processing" % (lib_id, exp_id, map_id)
    else:
        print "%s_e%s_m%s_ucsc : E BED file : start" % (lib_id, exp_id, map_id)
        open(e_filename_ucsc, "wt").close() # touch E BED (processing)
        e = pybio.data.Bedgraph()
        e.overlay(polyadb_filename, r_filename, region_up=100, region_down=25)
        e.save(e_filename_ucsc, genome=map_to, track_id="%s_e%s_m1" % (lib_id, exp_id))

def bed_expression_paseqx(lib_id, exp_id, map_id, map_to, polyid, force=False):
    genome = apa.annotation.libs[lib_id].experiments[exp_id]["map_to"]
    r_filename = apa.path.r_filename(lib_id, exp_id)
    if polyid==None:
        polyid = map_to
    polyadb_filename = apa.path.polyadb_filename(polyid)

    if type(apa.config.process)==list and map_to not in apa.config.process:
        return

    e_filename = apa.path.e_filename(lib_id, exp_id)
    if os.path.exists(e_filename) and not force:
        print "%s_e%s_m%s_ucsc : E BED : already processed or currently processing" % (lib_id, exp_id, map_id)
    else:
        print "%s_e%s_m%s_ucsc : E BED file : start" % (lib_id, exp_id, map_id)
        open(e_filename, "wt").close() # touch E BED (processing)
        e = pybio.data.Bedgraph()
        e.overlay(polyadb_filename, r_filename, region_up=100, region_down=25)
        e.save(e_filename, track_id="%s_e%s_m1" % (lib_id, exp_id))
__copyright__ = "Copyright 2016, Netflix, Inc."
__license__ = "Apache, Version 2.0"

import re
import subprocess
import numpy as np

import config
from core.executor import Executor
from core.result import Result


class FeatureExtractor(Executor):
    """
    FeatureExtractor takes in a list of assets, and run feature extraction on
    them, and return a list of corresponding results. A FeatureExtractor must
    specify a unique type and version combination (by the TYPE and VERSION
    attribute), so that the Result generated by it can be identified.

    A derived class of FeatureExtractor must:
        1) Override TYPE and VERSION
        2) Override _run_and_generate_log_file(self, asset), which call a
        command-line executable and generate feature scores in a log file.
        3) Override _get_feature_scores(self, asset), which read the feature
        scores from the log file, and return the scores in a dictionary format.
    For an example, follow VmafFeatureExtractor.
    """

    def _read_result(self, asset):
        result = {}
        result.update(self._get_feature_scores(asset))
        return Result(asset, self.executor_id, result)

    @classmethod
    def get_scores_key(cls, atom_feature):
        return "{type}_{atom_feature}_scores".format(
            type=cls.TYPE, atom_feature=atom_feature)

    @classmethod
    def get_score_key(cls, atom_feature):
        return "{type}_{atom_feature}_score".format(
            type=cls.TYPE, atom_feature=atom_feature)

class VmafFeatureExtractor(FeatureExtractor):

    TYPE = "VMAF_feature"

    # VERSION = '0.1' # vmaf_study; Anush's VIF fix
    VERSION = '0.2' # expose vif_num, vif_den, adm_num, adm_den, anpsnr

    ATOM_FEATURES = ['vif', 'adm', 'ansnr', 'motion',
                     'vif_num', 'vif_den', 'adm_num', 'adm_den', 'anpsnr']

    VMAF_FEATURE = config.ROOT + "/feature/vmaf"

    ADM_CONSTANT = 1000

    def _run_and_generate_log_file(self, asset):
        # routine to call the command-line executable and generate feature
        # scores in the log file.

        log_file_path = self._get_log_file_path(asset)

        # run VMAF command line to extract features, APPEND (>>) result (since
        # _prepare_generate_log_file method has already created the file and
        # written something in advance).
        quality_width, quality_height = asset.quality_width_height
        vmaf_feature_cmd = "{vmaf} all {yuv_type} {ref_path} {dis_path} {w} {h} >> {log_file_path}" \
        .format(
            vmaf=self.VMAF_FEATURE,
            yuv_type=asset.yuv_type,
            ref_path=asset.ref_workfile_path,
            dis_path=asset.dis_workfile_path,
            w=quality_width,
            h=quality_height,
            log_file_path=log_file_path,
        )

        if self.logger:
            self.logger.info(vmaf_feature_cmd)

        subprocess.call(vmaf_feature_cmd, shell=True)

    def _get_feature_scores(self, asset):
        # routine to read the feature scores from the log file, and return
        # the scores in a dictionary format.

        log_file_path = self._get_log_file_path(asset)

        atom_feature_scores_dict = {}
        atom_feature_idx_dict = {}
        for atom_feature in self.ATOM_FEATURES:
            atom_feature_scores_dict[atom_feature] = []
            atom_feature_idx_dict[atom_feature] = 0

        with open(log_file_path, 'rt') as log_file:
            for line in log_file.readlines():
                for atom_feature in self.ATOM_FEATURES:
                    re_template = "{af}: ([0-9]+) ([0-9.-]+)".format(af=atom_feature)
                    mo = re.match(re_template, line)
                    if mo:
                        cur_idx = int(mo.group(1))
                        assert cur_idx == atom_feature_idx_dict[atom_feature]
                        atom_feature_scores_dict[atom_feature].append(float(mo.group(2)))
                        atom_feature_idx_dict[atom_feature] += 1
                        continue

        len_score = len(atom_feature_scores_dict[self.ATOM_FEATURES[0]])
        assert len_score != 0
        for atom_feature in self.ATOM_FEATURES[1:]:
            assert len_score == len(atom_feature_scores_dict[atom_feature]), \
                "Feature data possibly corrupt. Run cleanup script and try again."

        feature_result = {}

        for atom_feature in self.ATOM_FEATURES:
            scores_key = self.get_scores_key(atom_feature)
            feature_result[scores_key] = atom_feature_scores_dict[atom_feature]

        return feature_result

    @classmethod
    def _post_process_result(cls, result):
        # override Executor._Post_process_result(result)

        # replace adm score with:
        # (adm_num + ADM_CONSTANT) / (adm_den + ADM_CONSTANT)
        adm_scores_key = cls.get_scores_key('adm')
        adm_num_scores_key = cls.get_scores_key('adm_num')
        adm_den_scores_key = cls.get_scores_key('adm_den')
        result.result_dict[adm_scores_key] = list(
            (np.array(result.result_dict[adm_num_scores_key]) + cls.ADM_CONSTANT) /
            (np.array(result.result_dict[adm_den_scores_key]) + cls.ADM_CONSTANT)
        )

        return result

class PsnrFeatureExtractor(FeatureExtractor):

    TYPE = "PSNR_feature"
    VERSION = "1.0"

    ATOM_FEATURES = ['psnr']

    PSNR = config.ROOT + "/feature/psnr"

    def _run_and_generate_log_file(self, asset):
        # routine to call the command-line executable and generate quality
        # scores in the log file.

        log_file_path = self._get_log_file_path(asset)

        # run VMAF command line to extract features, 'APPEND' result (since
        # super method already does something
        quality_width, quality_height = asset.quality_width_height
        psnr_cmd = "{psnr} {yuv_type} {ref_path} {dis_path} {w} {h} >> {log_file_path}" \
        .format(
            psnr=self.PSNR,
            yuv_type=asset.yuv_type,
            ref_path=asset.ref_workfile_path,
            dis_path=asset.dis_workfile_path,
            w=quality_width,
            h=quality_height,
            log_file_path=log_file_path,
        )

        if self.logger:
            self.logger.info(psnr_cmd)

        subprocess.call(psnr_cmd, shell=True)

    def _get_feature_scores(self, asset):
        # routine to read the feature scores from the log file, and return
        # the scores in a dictionary format.

        log_file_path = self._get_log_file_path(asset)

        psnr_scores = []
        counter = 0
        with open(log_file_path, 'rt') as log_file:
            for line in log_file.readlines():
                mo = re.match(r"psnr: ([0-9]+) ([0-9.-]+)", line)
                if mo:
                    cur_idx = int(mo.group(1))
                    assert cur_idx == counter
                    psnr_scores.append(float(mo.group(2)))
                    counter += 1

        assert len(psnr_scores) != 0

        feature_result = {}

        assert len(self.ATOM_FEATURES) == 1
        atom_feature = self.ATOM_FEATURES[0]
        scores_key = self.get_scores_key(atom_feature)
        feature_result[scores_key] = psnr_scores

        return feature_result


class MomentFeatureExtractor(FeatureExtractor):

    TYPE = "Moment_feature"
    VERSION = "1.0"

    ATOM_FEATURES = ['ref1st', 'ref2nd', 'refvar', 'dis1st', 'dis2nd', 'disvar']

    MOMENT = config.ROOT + "/feature/moment"

    def _run_and_generate_log_file(self, asset):
        # routine to call the command-line executable and generate feature
        # scores in the log file.

        log_file_path = self._get_log_file_path(asset)

        quality_width, quality_height = asset.quality_width_height

        # run MOMENT command line to extract features, APPEND (>>) result (since
        # _prepare_generate_log_file method has already created the file and
        # written something in advance).
        with open(log_file_path, 'at') as log_file:
            log_file.write("=== ref: ===\n")
        ref_moment_cmd = "{moment} 2 {yuv_type} {ref_path} {w} {h} >> {log_file_path}" \
        .format(
            moment=self.MOMENT,
            yuv_type=asset.yuv_type,
            ref_path=asset.ref_workfile_path,
            w=quality_width,
            h=quality_height,
            log_file_path=log_file_path,
        )
        if self.logger:
            self.logger.info(ref_moment_cmd)
        subprocess.call(ref_moment_cmd, shell=True)

        with open(log_file_path, 'at') as log_file:
            log_file.write("=== dis: ===\n")
        dis_moment_cmd = "{moment} 2 {yuv_type} {dis_path} {w} {h} >> {log_file_path}" \
        .format(
            moment=self.MOMENT,
            yuv_type=asset.yuv_type,
            dis_path=asset.dis_workfile_path,
            w=quality_width,
            h=quality_height,
            log_file_path=log_file_path,
        )
        if self.logger:
            self.logger.info(dis_moment_cmd)
        subprocess.call(dis_moment_cmd, shell=True)

    def _get_feature_scores(self, asset):
        # routine to read the feature scores from the log file, and return
        # the scores in a dictionary format.

        log_file_path = self._get_log_file_path(asset)

        atom_feature_scores_dict = {}
        atom_feature_idx_dict = {}
        for atom_feature in self.ATOM_FEATURES:
            atom_feature_scores_dict[atom_feature] = []
            atom_feature_idx_dict[atom_feature] = 0

        # read ref1st, ref2nd, dis1st, dis2nd
        ref_or_dis = None
        with open(log_file_path, 'rt') as log_file:
            for line in log_file.readlines():
                mo = re.match(r"=== ref: ===", line)
                if mo:
                    ref_or_dis = 'ref'
                    continue

                mo = re.match(r"=== dis: ===", line)
                if mo:
                    ref_or_dis = 'dis'
                    continue

                mo = re.match(r"1stmoment: ([0-9]+) ([0-9.-]+)", line)
                if mo:
                    cur_idx = int(mo.group(1))
                    assert ref_or_dis is not None
                    atom_feature = ref_or_dis + '1st'
                    assert cur_idx == atom_feature_idx_dict[atom_feature]
                    atom_feature_scores_dict[atom_feature].append(float(mo.group(2)))
                    atom_feature_idx_dict[atom_feature] += 1
                    continue

                mo = re.match(r"2ndmoment: ([0-9]+) ([0-9.-]+)", line)
                if mo:
                    cur_idx = int(mo.group(1))
                    assert ref_or_dis is not None
                    atom_feature = ref_or_dis + '2nd'
                    assert cur_idx == atom_feature_idx_dict[atom_feature]
                    atom_feature_scores_dict[atom_feature].append(float(mo.group(2)))
                    atom_feature_idx_dict[atom_feature] += 1
                    continue

        # calculate refvar and disvar from ref1st, ref2nd, dis1st, dis2nd
        get_var = lambda (m1, m2): m2 - m1 * m1
        atom_feature_scores_dict['refvar'] = \
            map(get_var, zip(atom_feature_scores_dict['ref1st'],
                             atom_feature_scores_dict['ref2nd']))
        atom_feature_scores_dict['disvar'] = \
            map(get_var, zip(atom_feature_scores_dict['dis1st'],
                             atom_feature_scores_dict['dis2nd']))

        # assert lengths
        len_score = len(atom_feature_scores_dict[self.ATOM_FEATURES[0]])
        assert len_score != 0
        for atom_feature in self.ATOM_FEATURES[1:]:
            assert len_score == len(atom_feature_scores_dict[atom_feature])

        feature_result = {}

        for atom_feature in self.ATOM_FEATURES:
            scores_key = self.get_scores_key(atom_feature)
            feature_result[scores_key] = atom_feature_scores_dict[atom_feature]

        return feature_result


import matplotlib.pyplot as plt
from open_fdd.air_handling_unit.reports.base_report import BaseReport
import pandas as pd
import sys

class FaultCodeThreeReport(BaseReport):
    def __init__(self, config):
        super().__init__(config)
        self.mix_degf_err_thres = config['MIX_DEGF_ERR_THRES']
        self.return_degf_err_thres = config['RETURN_DEGF_ERR_THRES']
        self.outdoor_degf_err_thres = config['OUTDOOR_DEGF_ERR_THRES']
        self.mat_col = config['MAT_COL']
        self.rat_col = config['RAT_COL']
        self.oat_col = config['OAT_COL']
        self.supply_vfd_speed_col = config['SUPPLY_VFD_SPEED_COL']


    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc3_flag"

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle('Fault Conditions 3 Plot')

        ax1.plot(df.index, df[self.mat_col], color='r', label="Mix Temp")  # red
        ax1.plot(df.index, df[self.rat_col], color='b', label="Return Temp")  # blue
        ax1.plot(df.index, df[self.oat_col], color='g', label="Out Temp")  # green
        ax1.legend(loc='best')
        ax1.set_ylabel("°F")

        ax2.plot(df.index, df[output_col], label="Fault", color="k")
        ax2.set_xlabel('Date')
        ax2.set_ylabel('Fault Flags')
        ax2.legend(loc='best')

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc3_flag"):
        # Display report content in IPython
        print("Fault Condition 3: Mix temperature too high; should be between outside and return air")

        # Display plot
        self.create_plot(df, output_col)

        # Display summary statistics
        summary = self.summarize_fault_times(df, output_col)
        print(summary)

        fc_max_faults_found = df[output_col].max()

        print("flag_count: ", fc_max_faults_found)
        sys.stdout.flush()

        if fc_max_faults_found != 0:
            print("Time-of-day Histogram Plots")
            self.create_hist_plot(df, output_col)

            flag_true_mat = round(
                df[self.mat_col].where(df[output_col] == 1).mean(), 2
            )
            print("flag_true_mat: ", flag_true_mat)

            flag_true_oat = round(
                df[self.oat_col].where(df[output_col] == 1).mean(), 2
            )
            print("flag_true_oat: ", flag_true_oat)

            flag_true_rat = round(
                df[self.rat_col].where(df[output_col] == 1).mean(), 2
            )
            print("flag_true_rat: ", flag_true_rat)

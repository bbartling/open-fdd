from open_fdd.air_handling_unit.reports.base_report import BaseReport
import matplotlib.pyplot as plt
import pandas as pd
import sys

class FaultCodeFourReport(BaseReport):
    """Class provides the definitions for Fault Code 4 Report.
    Reporting the time series avg df that calculates control states per hour.
    """

    def __init__(self, config):
        super().__init__(config)
        self.delta_os_max = config['DELTA_OS_MAX']
        self.heating_mode_calc_col = 'heating_mode'
        self.econ_only_cooling_mode_calc_col = 'econ_only_cooling_mode'
        self.econ_plus_mech_cooling_mode_calc_col = 'econ_plus_mech_cooling_mode'
        self.mech_cooling_only_mode_calc_col = 'mech_cooling_only_mode'

    def summarize_fc4_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "fc4_flag"

        # Calculate dataset statistics
        delta_all_data = df.index.to_series().diff()

        total_days_all_data = round(delta_all_data.sum() / pd.Timedelta(days=1), 2)
        total_hours_all_data = delta_all_data.sum() / pd.Timedelta(hours=1)
        hours_fc4_mode = (delta_all_data * df[output_col]).sum() / pd.Timedelta(hours=1)
        percent_true_fc4 = round(df.fc4_flag.mean() * 100, 2)
        percent_false_fc4 = round((100 - percent_true_fc4), 2)

        # Heating mode runtime stats
        delta_heating = df[self.heating_mode_calc_col].index.to_series().diff()
        total_hours_heating = (delta_heating * df[self.heating_mode_calc_col]).sum() / pd.Timedelta(hours=1)
        percent_heating = round(df[self.heating_mode_calc_col].mean() * 100, 2)

        # Econ mode runtime stats
        delta_econ = df[self.econ_only_cooling_mode_calc_col].index.to_series().diff()
        total_hours_econ = (delta_econ * df[self.econ_only_cooling_mode_calc_col]).sum() / pd.Timedelta(hours=1)
        percent_econ = round(df[self.econ_only_cooling_mode_calc_col].mean() * 100, 2)

        # Econ plus mech cooling mode runtime stats
        delta_econ_clg = df[self.econ_plus_mech_cooling_mode_calc_col].index.to_series().diff()
        total_hours_econ_clg = (delta_econ_clg * df[self.econ_plus_mech_cooling_mode_calc_col]).sum() / pd.Timedelta(hours=1)
        percent_econ_clg = round(df[self.econ_plus_mech_cooling_mode_calc_col].mean() * 100, 2)

        # Mech clg mode runtime stats
        delta_clg = df[self.mech_cooling_only_mode_calc_col].index.to_series().diff()
        total_hours_clg = (delta_clg * df[self.mech_cooling_only_mode_calc_col]).sum() / pd.Timedelta(hours=1)
        percent_clg = round(df[self.mech_cooling_only_mode_calc_col].mean() * 100, 2)

        return {
            "total_days_all_data": total_days_all_data,
            "total_hours_all_data": total_hours_all_data,
            "hours_fc4_mode": hours_fc4_mode,
            "percent_true_fc4": percent_true_fc4,
            "percent_false_fc4": percent_false_fc4,
            "percent_clg": percent_clg,
            "percent_econ_clg": percent_econ_clg,
            "percent_econ": percent_econ,
            "percent_heating": percent_heating,
            "total_hours_heating": total_hours_heating,
            "total_hours_econ": total_hours_econ,
            "total_hours_econ_clg": total_hours_econ_clg,
            "total_hours_clg": total_hours_clg
        }

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc4_flag"

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        plt.title('Fault Conditions 4 Plots')

        ax1.plot(df.index, df[self.heating_mode_calc_col], label="Heat", color='orange')
        ax1.plot(df.index, df[self.econ_only_cooling_mode_calc_col], label="Econ Clg", color='olive')
        ax1.plot(df.index, df[self.econ_plus_mech_cooling_mode_calc_col], label="Econ + Mech Clg", color='c')
        ax1.plot(df.index, df[self.mech_cooling_only_mode_calc_col], label="Mech Clg", color='m')

        ax1.set_xlabel('Date')
        ax1.set_ylabel('Calculated AHU Operating States')
        ax1.legend(loc='best')

        ax2.plot(df.index, df[output_col], label="Fault", color="k")
        ax2.set_xlabel('Date')
        ax2.set_ylabel('Fault Flags')
        ax2.legend(loc='best')

        plt.tight_layout()
        plt.show()
        plt.close()


    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc4_flag"):
        # Display report content in IPython
        print("Fault Condition 4: Hunting too many OS state changes")

        # Display plot
        self.create_plot(df, output_col)

        # Display summary statistics
        summary = self.summarize_fc4_fault_times(df, output_col)
        print(summary)

        fc_max_faults_found = df[output_col].max()

        print("flag_count: ", fc_max_faults_found)
        sys.stdout.flush()

        if fc_max_faults_found != 0:
            print("Time-of-day Histogram Plots")
            self.create_hist_plot(df, output_col)
            sys.stdout.flush()

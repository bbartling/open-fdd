import matplotlib.pyplot as plt
import pandas as pd
from io import BytesIO
import sys

class BaseReport:
    def __init__(self, config):
        self.config = config

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str) -> dict:
        delta = df.index.to_series().diff().dt.total_seconds()
        total_days = round(delta.sum() / 86400, 2)
        total_hours = round(delta.sum() / 3600, 2)
        hours_fault_mode = (delta * df[output_col]).sum() / 3600
        percent_true = round(df[output_col].mean() * 100, 2)
        percent_false = round((100 - percent_true), 2)

        # Calculate motor runtime
        motor_on = df[self.config['SUPPLY_VFD_SPEED_COL']].gt(.01).astype(int)
        hours_motor_runtime = round((delta * motor_on).sum() / 3600, 2)

        summary = {
            'total_days': total_days,
            'total_hours': total_hours,
            'hours_fault_mode': hours_fault_mode,
            'percent_true': percent_true,
            'percent_false': percent_false,
            'hours_motor_runtime': hours_motor_runtime
        }
        print("SUMMARY: ", summary)
        return summary

    def create_hist_plot(self, df: pd.DataFrame, output_col: str):
        df["hour_of_the_day"] = df.index.hour.where(df[output_col] == 1)
        df = df.dropna(subset=["hour_of_the_day"])
        print(df["hour_of_the_day"])
        sys.stdout.flush()

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day.dropna(), bins=24)
        ax.set_xlabel("Hour of the Day")
        ax.set_ylabel("Frequency")
        ax.set_title("Hour-Of-Day When Fault Flag is TRUE")
        plt.show()
        plt.close()

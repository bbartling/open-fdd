import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import sys


class BaseFaultReport:
    def __init__(self, config, fault_col):
        self.config = config
        self.fault_col = fault_col

    def create_plot(self, df: pd.DataFrame):
        raise NotImplementedError

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        raise NotImplementedError

    def create_hist_plot(self, df: pd.DataFrame):
        df[f"hour_of_the_day_{self.fault_col}"] = df.index.hour.where(
            df[self.fault_col] == 1
        )
        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df[f"hour_of_the_day_{self.fault_col}"].dropna())
        ax.set_xlabel("Hour of the Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag {self.fault_col} is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame):
        summary = self.summarize_fault_times(df)
        for key, value in summary.items():
            formatted_key = key.replace("_", " ")
            print(f"{formatted_key}: {value}")
            sys.stdout.flush()

        if df[self.fault_col].max() != 0:
            self.create_plot(df)
            self.create_hist_plot(df)
        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()

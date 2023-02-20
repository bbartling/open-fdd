# import argparse
import os

import pandas as pd

from faults import FaultConditionOne, FaultConditionTwo
from reports import FaultCodeOneReport, FaultCodeTwoReport
import click


# python 3.10 on Windows 10
# py .\fc1.py -i ./ahu_data/hvac_random_fake_data/fc1_fake_data1.csv -o fake1_ahu_fc1_report


@click.group()
@click.option("--debug/--no-debug", default=False)
def cli(debug):
    click.echo(f"Debug mode is {'on' if debug else 'off'}")


@cli.command()
@click.option("-i", "--input", required=True, type=str, help="CSV File Input")
@click.option("-o", "--output", required=True, type=str, help="Word File Output Name")
@click.option(
    "--vfd-speed-percent-err-thres",
    default=0.05,
    type=float,
    help="VFD Speed Percent Error Threshold",
)
@click.option(
    "--vfd-speed-percent-max", default=0.99, type=float, help="VFD Speed Percent Max"
)
@click.option(
    "--duct-static-inches-err-thres",
    default=0.1,
    type=float,
    help="Duct Static Inches Error Threshold",
)
@click.option(
    "--duct-static-col", default="duct_static", type=str, help="Duct Static Column Name"
)
@click.option(
    "--duct-static-setpoint-col",
    default="duct_static_setpoint",
    type=str,
    help="Duct Static Setpoint Column Name",
)
@click.option(
    "--vfd-speed-col",
    default="supply_vfd_speed",
    type=str,
    help="VFD Speed Column Name",
)
def check_fault_one(
    input,
    output,
    vfd_speed_percent_err_thres,
    vfd_speed_percent_max,
    duct_static_inches_err_thres,
    duct_static_col,
    duct_static_setpoint_col,
    vfd_speed_col,
):
    """
    FUTURE
    * incorporate an arg for SI units
    * °C on temp sensors
    * piping pressure sensor PSI conversion
    * air flow CFM conversion
    * AHU duct static pressure "WC

    args.add_argument('--use-SI-units', default=False, action='store_true')
    args.add_argument('--no-SI-units', dest='use-SI-units', action='store_false')
    """
    _fc1 = FaultConditionOne(
        vfd_speed_percent_err_thres,
        vfd_speed_percent_max,
        duct_static_inches_err_thres,
        duct_static_col,
        vfd_speed_col,
        duct_static_setpoint_col,
    )
    _fc1_report = FaultCodeOneReport(
        vfd_speed_percent_err_thres,
        vfd_speed_percent_max,
        duct_static_inches_err_thres,
        duct_static_col,
        vfd_speed_col,
        duct_static_setpoint_col,
    )

    df = pd.read_csv(input, index_col="Date", parse_dates=True).rolling("5T").mean()

    df[duct_static_setpoint_col] = 1

    start = df.head(1).index.date
    print("Dataset start: ", start)

    end = df.tail(1).index.date
    print("Dataset end: ", end)

    for col in df.columns:
        print("df column: ", col, "- max len: ", df[col].size)

    # return a whole new dataframe with fault flag as new col
    df2 = _fc1.apply(df)
    print(df2.head())
    print(df2.describe())

    document = _fc1_report.create_report(output, df)
    path = os.path.join(os.path.curdir, "final_report")
    if not os.path.exists(path):
        os.makedirs(path)
    document.save(os.path.join(path, f"{output}.docx"))


@cli.command()
@click.option("-i", "--input", required=True, type=str, help="CSV File Input")
@click.option("-o", "--output", required=True, type=str, help="Word File Output Name")
@click.option("--outdoor-degf-err-thres", default=5., type=float, help="Outdoor DegF Error Threshold")
@click.option("--mix-degf-err-thres", default=5., type=float, help="Mix DegF Error Threshold")
@click.option("--return-degf-err-thres", default=2., type=float, help="Return DegF Error Threshold")
@click.option("--outdoor-temp-f-col", default="oat", type=str, help="Outdoor DegF Column Name")
@click.option("--mix-temp-f-col", default="mat", type=str, help="Mix DegF Column Name")
@click.option("--return-temp-f-col", default="rat", type=str, help="Return DegF Column Name")
def check_fault_two( input, output, outdoor_degf_err_thres, mix_degf_err_thres, return_degf_err_thres, outdoor_temp_f_col, mix_temp_f_col, return_temp_f_col):
    """
    FUTURE 
    * incorporate an arg for SI units 
    * °C on temp sensors
    * piping pressure sensor PSI conversion
    * air flow CFM conversion
    * AHU duct static pressure "WC

    args.add_argument('--use-SI-units', default=False, action='store_true')
    args.add_argument('--no-SI-units', dest='use-SI-units', action='store_false')
    """

    _fc2 = FaultConditionTwo(
        outdoor_degf_err_thres,
        mix_degf_err_thres,
        return_degf_err_thres,
        mix_temp_f_col,
        return_temp_f_col,
        outdoor_temp_f_col,
    )
    _fc2_report = FaultCodeTwoReport(
        outdoor_degf_err_thres,
        mix_degf_err_thres,
        return_degf_err_thres,
        mix_temp_f_col,
        return_temp_f_col,
        outdoor_temp_f_col,
    )


    df = pd.read_csv(input, index_col="Date", parse_dates=True).rolling("5T").mean()

    start = df.head(1).index.date
    print("Dataset start: ", start)

    end = df.tail(1).index.date
    print("Dataset end: ", end)

    for col in df.columns:
        print("df column: ", col, "- max len: ", df[col].size)
        

    # return a whole new dataframe with fault flag as new col
    df2 = _fc2.apply(df)
    print(df2.head())
    print(df2.describe())

    document = _fc2_report.create_report(output, df)
    path = os.path.join(os.path.curdir, "final_report")
    if not os.path.exists(path):
        os.makedirs(path)
    document.save(os.path.join(path, f"{output}.docx"))


if __name__ == "__main__":
    cli()
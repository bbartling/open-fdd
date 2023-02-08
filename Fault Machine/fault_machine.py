import operator, time
import pandas as pd
import numpy as np



class FaultMachine():
    
    def __init__(self,df):
        self.df = df
        self.vfd_speed_percent_err_thres = .05
        self.duct_static_inches_err_thres = .99
        self.vfd_speed_percent_max = .1
        self.duct_static_pressure_setpoint = 1.
        self.outdoor_degf_err_thres = 5.
        self.mix_degf_err_thres = 5.
        self.return_degf_err_thres =  2.


    def fault_condition_one(self,df):
        return operator.and_(df.duct_static < (df.duct_static_setpoint - df.duct_static_inches_err_thres),
                            df.supply_vfd_speed > (df.vfd_speed_percent_max - df.vfd_speed_percent_err_thres))

    def fault_condition_two(self,df):
        return ((df.mat + df.mix_degf_err_thres) < np.minimum((df.rat - df.return_degf_err_thres),
                                                                            (df.oat - df.outdoor_degf_err_thres)))
    def fault_condition_three(self,df):
        return ((df.mat - df.mix_degf_err_thres) > np.maximum((df.rat + df.return_degf_err_thres),
                                                                            (df.oat + df.outdoor_degf_err_thres)))
    def fault_condition_four(self,df):
        return #TODO make FC4 method, currently doesnt have one for OS state change calcs
        
    def fault_condition_five(self,df):
        return ((df.sat + df.supply_degf_err_thres) <= (df.mat - df.mix_degf_err_thres + df.delta_t_supply_fan))
    
    def fault_condition_six(self,df):
        return operator.and_(df.rat_minus_oat >= df.oat_rat_delta_min,
                            df.percent_oa_calc_minus_perc_OAmin > df.airflow_err_thres)    
     
    def fault_condition_seven(self,df):
        return operator.and_(df.sat < df.satsp - df.sat_degf_err_thres,
                            df.htg >= 99)
        
    def fault_condition_eight(self,df):
        return df.sat_fan_mat > df.sat_mat_sqrted
    
    def fault_condition_nine(self,df):
        return df.oat_minus_oaterror > df.satsp_delta_saterr
    
    def fault_condition_ten(self,df):
        return df.abs_mat_minus_oat > df.mat_oat_sqrted
    
    def fault_condition_eleven(self,df):
        return df.oat_minus_oaterror < df.satsp_delta_saterr

    def fault_condition_twelve(self,df):
        return df.sat_minus_saterr_delta_supply_fan >= df.mat_plus_materr
    
    def fault_condition_thirteen(df):
        return operator.and_(df.sat > df.satsp - df.sat_degf_err_thres,
                            df.clg >= 99)
    
    def run_analysis(self):
        df = pd.read_csv(self.df,
                        index_col='Date',
                        parse_dates=True).rolling('5T').mean()

        start = df.head(1).index.date
        print('Dataset start: ', start)

        end = df.tail(1).index.date
        print('Dataset end: ', end)

        # FC1 params
        df['vfd_speed_percent_err_thres'] = self.vfd_speed_percent_err_thres
        df['duct_static_inches_err_thres'] = self.duct_static_inches_err_thres
        df['vfd_speed_percent_max'] = self.vfd_speed_percent_max
        df['duct_static_setpoint'] = self.duct_static_pressure_setpoint

        for col in df.columns:
            print('df column: ',col, 'max len: ', df[col].size)
            
        df['fc1_flag'] = self.fault_condition_one(df)

        df = df.copy().dropna()
        df['fc1_flag'] = df['fc1_flag'].astype(int)

        # drop params column for better plot
        df = df.drop(['vfd_speed_percent_err_thres',
                        'duct_static_inches_err_thres',
                        'vfd_speed_percent_max'], axis=1)

        print('fc1 done!')
        print(df.fc1_flag)
        print(df)
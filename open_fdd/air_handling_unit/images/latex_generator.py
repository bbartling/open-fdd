import streamlit as st


# On windows 10 python 3.10.6
# py -3.10 -m streamlit run .\latex_generator.py

# display Fault Equation 1
st.title("Fault Equation 1")
st.caption("Duct static pressure too low with fan at full speed")
st.latex(
    r"""
    DSP < DPSP - eDSP \quad \text{and} \quad VFDSPD \geq 99\% - eVFDSPD
    """
)

# Display legend
st.markdown("Legend:")
st.markdown("- DSP: Duct Static Pressure")
st.markdown("- DPSP: Duct Static Pressure Setpoint")
st.markdown("- VFDSPD: VFD Speed Reference in Percent")
st.markdown("- eVFDSPD: VFD Speed Reference Error Threshold")


# display Fault Equation 2
st.title("Fault Equation 2")
st.caption('Mix air temperature too low; should be between outside and return')
st.latex(r'''
    MAT_{avg} + eMAT < \min[(RAT_{avg} - eRAT), - OAT_{avg} - eOAT)]
    ''')


# display Fault Equation 3
st.title("Fault Equation 3")
st.caption('Mix air temperature too high; should be between outside and return')
st.latex(r'''
    MAT_{avg} - eMAT > \min[(RAT_{avg} + eRAT), - OAT_{avg} + eOAT)]
    ''')

        
# display Fault Equation 4
st.title("Fault Equation 4")
st.caption('Too many AHU operating state changes due to PID hunting and/or excessive cycling during low load conditions.')
st.latex(r'''
    \Delta OS > \Delta OS_{max}
    ''')


# display Fault Equation 5
st.title("Fault Equation 5")
st.caption('Supply air temperature too high')
st.latex(r'''
    SAT_{avg} + eSAT \leq MAT_{avg} - eMAT + \Delta TSF
    ''')


# display Fault Equation 6
st.title("Fault Equation 6")
st.caption('Temperature and outside air percentage deviation from setpoints')
st.latex(r'''
    |\text{RAT}_{\text{avg}} - \text{OAT}_{\text{avg}}| \geq \Delta T_{\text{min}} \quad \text{and} \quad |\%OA - \%OA_{\text{min}}| > eF
    ''')


# display Fault Equation 7
st.title("Fault Equation 7")
st.caption('Supply air temperature too low and heating coil status')
st.latex(r'''
    \text{SAT}_{\text{avg}} < \text{SATSP} - eSAT \quad \text{and} \quad \text{HC} \geq 99\%
    ''')

# display Fault Equation 8
st.title("Fault Equation 8")
st.caption('Deviation between supply air temperature and mixed air temperature')
st.latex(r'''
    | \text{SAT}_{\text{avg}} - \Delta \text{TSF} - \text{MAT}_{\text{avg}} | > \sqrt{{eSAT}^2 + {eMAT}^2}
    ''')


# display Fault Equation 9
st.title("Fault Equation 9")
st.caption('Outside air temperature deviation from setpoint')
st.latex(r'''
    \text{OAT}_{\text{avg}} - eOAT > \text{SATSP} - \Delta \text{SF} + eSAT
    ''')

# display Fault Equation 10
st.title("Fault Equation 10")
st.caption('Temperature difference between mixed air and outside air')
st.latex(r'''
    | \text{MAT}_{\text{avg}} - \text{OAT}_{\text{avg}} | > \sqrt{eMAT^2 + eOAT^2}
    ''')

# display Fault Equation 11
st.title("Fault Equation 11")
st.caption('Outside air temperature and supply air temperature deviation')
st.latex(r'''
    \text{OAT}_{\text{avg}} + eOAT < \text{SATSP} - \Delta \text{TSF} - eSAT
    ''')

# display Fault Equation 12
st.title("Fault Equation 12")
st.caption('Supply air temperature deviation from mixed air temperature')
st.latex(r'''
    \text{SAT}_{\text{avg}} - eSAT - \Delta \text{TSF} \geq \text{MAT}_{\text{avg}} + eMAT
    ''')

# display Fault Equation 13
st.title("Fault Equation 13")
st.caption('Supply air temperature too high')
st.latex(r'''
    \text{SAT}_{\text{avg}} < \text{SATSP} + eSAT \quad \text{and} \quad \text{CC} \geq 99\%
    ''')


st.title("find_closest_weather_dates Function")
st.caption('Finding closest weather dates based on given criteria')
st.latex(r'''
1. A' = \{a \in A : a < d_{test}\} \\
2. B' = \{b \in B : b < d_{test}\} \\
3. C = \{a \in A' : a \notin B'\} \\
4. \text{if } |C| < 10 \text{ then remove } \max(A') \text{ and repeat step 3} \\
5. A = A \cap C, \text{calculate } \mu(A)
''')
st.caption('''
In this notation:
- $A$ represents the "all_data" dataset.
- $B$ represents the "suitable_baseline_no" dataset.
- $d_{test}$ is the "test_case_date".
- $A'$ and $B'$ are subsets of $A$ and $B$ that only include dates prior to $d_{test}$.
- $C$ is a set of dates in $A'$ not found in $B'$.
- $|C|$ represents the count of elements in set $C$.
- $\max(A')$ is the latest date in $A'$.
- $\mu(A)$ is the mean of the remaining elements in $A$ after filtering by set $C$.
''')


st.title("find_previous_10_days Function")
st.caption('Finding previous 10 weekdays based on given criteria')
st.latex(r'''
1. A' = \{a \in A : a < d_{test}\} \\
2. B' = \{b \in B : b < d_{test}\} \\
3. C = \{a \in A' : a \notin B'\} \\
4. \text{if } |C| < 10 \text{ then remove } \max(A') \text{ and repeat step 3} \\
5. A = A \cap C
''')
st.caption('''
In this notation:
- $A$ represents the "all_data" dataset.
- $B$ represents the "suitable_baseline_no" dataset.
- $d_{test}$ is the "test_case_date".
- $A'$ and $B'$ are subsets of $A$ and $B$ that only include dates prior to $d_{test}$.
- $C$ is a set of dates in $A'$ not found in $B'$.
- $|C|$ represents the count of elements in set $C$.
- $\max(A')$ is the latest date in $A'$.
''')


st.title("calculate_power_averages Function")
st.caption('Calculating average power for each type and time step')
st.latex(r'''
1. P_{type,i} = \{p : p \text{ is a power value at time step } t_i\} \quad \text{for each type and } i \in \{1,2,\dots,96\} \\
2. A_{type,i} = \frac{1}{|P_{type,i}|}\sum_{p \in P_{type,i}} p \quad \text{for each type and } i \in \{1,2,\dots,96\}
''')
st.caption('''
In this notation:
- $P_{type,i}$ represents the set of power values at time step $t_i$ for a specific power type (main, ahu, or solar).
- $p$ represents a power value in the set $P_{type,i}$.
- $|P_{type,i}|$ represents the count of elements in set $P_{type,i}$.
- $A_{type,i}$ represents the average power at time step $t_i$ for a specific power type.
''')






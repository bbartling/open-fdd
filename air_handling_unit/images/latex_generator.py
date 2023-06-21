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



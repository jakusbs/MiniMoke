import pyvisa

def lockin_drive():
    def Connection_Open_USB(sModelNumber, sSerialNumber):
        print('Open connection via USB')
        if (sModelNumber == '7270'):
            inst = rm.open_resource('USB0::0x0A2D::0x001B::' + sSerialNumber + '::RAW')
        return inst
    def Inst_Query_Command_USB(inst, sCmd):
        print('Send query command: ' + sCmd)
        inst.write_raw(sCmd)
        sResponse = inst.read()
        # read the status and overload bytes
        nStb = bytes((sResponse[len(sResponse)-2:len(sResponse)-1:]),'utf-8')
        nOvb = bytes((sResponse[len(sResponse)-1:len(sResponse):]),'utf-8')
        nStatusByte = int(nStb[0])
        # mask out bits 4, 5 & 6 which are not consistent across all instruments
        nStatusByte = nStatusByte & 143
        nOverloadByte = int(nOvb[0])
        # strip the returned response of the line feed, status & overload bytes, and 
        # the null terminator
        sResponse = sResponse[0:len(sResponse)-4:]
        # return the response from the instrument, the status byte, and the overload byte
        return sResponse, nStatusByte, nOverloadByte

    def Print_Status_Byte(nStatusByte):
        if (nStatusByte & 1 == 1):
            print('Command Done')
        if (nStatusByte & 2 == 2):
            print('Invalid command')
        if (nStatusByte & 4 == 4):
            print('Command parameter error')
        if (nStatusByte & 8 == 8):
            print('Reference unlock')
        # bits 4, 5 and 6 are instrument model number dependent so are
        # not decoded here
        if (nStatusByte & 128 == 128):
            print('Data Available')
    def Print_72XXOverload_Byte(nOverloadByte):
        if (nOverloadByte & 1 == 1):
            print('X(1) output overload')
        if (nOverloadByte & 2 == 2):
            print('Y(1) output overload')
        if (nOverloadByte & 4 == 4):
            print('X2 output overload')
        if (nOverloadByte & 8 == 8):
            print('Y2 output overload')
        if (nOverloadByte & 16 == 16):
            print('CH1 output overload')
        if (nOverloadByte & 32 == 32):
            print('CH2 output overload')
        if (nOverloadByte & 64 == 64):
            print('CH3 output overload')
        if (nOverloadByte & 128 == 128):
            print('CH4 output overload')
    def Connection_Close(inst):
        print('Close connection')
        inst.before_close()
        return_status = inst.close()
        return return_status

        
    # main code starts here     
    # from pyvisa.constants import StopBits, Parity
    rm = pyvisa.ResourceManager('C:/Windows/System32/visa32.dll') # 32 bit windows
    # rm = pyvisa.ResourceManager('C:/Windows/sysWOW64/visa32.dll') # 64 bit windows

    # Print the list of VISA resources on this computer
    rm.list_resources()
    print('The VISA resourses present on this computer are: ')
    print(rm.list_resources('?*'))
    # Demonstration of USB communications
    print('Demonstration of USB communications:')
    # open the connection with the specified instrument model and serial 
    # number (needed for USB)
    inst = Connection_Open_USB('7270', '15342534') # sSerialNumber can be found from list_resource 


    # send a command; returned tuple includes string response, if any, and 
    # integer status and overload bytes
    tReturn = Inst_Query_Command_USB(inst, "VER")
    # decode and print the meaning of the status byte
    Print_Status_Byte(tReturn[1])
    # decode and print the meaning of the overload byte
    Print_72XXOverload_Byte(tReturn[2])
    # if response was generated print it
    if (tReturn[0] != ''):
        print('Command response: ' + tReturn[0])
    else:
        print('Connection failed.')
        # close the connection
    Connection_Close(inst)
    print('\n')
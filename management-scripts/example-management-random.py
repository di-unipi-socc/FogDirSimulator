from APIWrapper import FogDirector
import time, random, math
from infrastructure import ciscorouter_size300_low_res as infrastructure
import requests
import json, signal

infrastructure.create()

tmp = 0
def bestFit(cpu, mem, print_result=False):
    _, devices = fg.get_devices()
    init = True
    devices = [ dev for dev in devices["data"] if dev["capabilities"]["nodes"][0]["cpu"]["available"] >= cpu and dev["capabilities"]["nodes"][0]["memory"]["available"] >= mem]
    devices.sort(reverse=True, key=(lambda dev: (dev["capabilities"]["nodes"][0]["cpu"]["available"], dev["capabilities"]["nodes"][0]["memory"]["available"]) ))
    if print_result:
        print("***********")
        for dev in devices:
            print(dev["ipAddress"], (dev["capabilities"]["nodes"][0]["cpu"]["available"], dev["capabilities"]["nodes"][0]["memory"]["available"]))
    if len(devices) == 0:
        print("THE SYSTEM HAS NO ENOUGH RESOURCES TO SUPPORT YOUR IDEA. SORRY.")
        return None
    best_fit = devices[0]
    return best_fit["ipAddress"]

def randomFit():
    _, devices = fg.get_devices()
    r = random.randint(0, len(devices["data"]) - 1)
    return devices["data"][r]["ipAddress"]

def firstFit(cpu, mem):
    _, devices = fg.get_devices()
    devices = [ dev for dev in devices["data"] if dev["capabilities"]["nodes"][0]["cpu"]["available"] >= cpu and dev["capabilities"]["nodes"][0]["memory"]["available"]]
    best_fit = devices[0]
    return best_fit["ipAddress"]

def FTpi_like(cpu, mem):
    # Not reasonable
    for _ in range(0, 1000):
        bestFit(cpu, mem) # requires 1 iteration for each counting => 1000 iteration for every device choice
    return None

def service_shutdown(*args):
    print('\nOh, ok, I will print the simulation result.Byeee!')
    r = reset_simulation("new")
    file_name = input("Filename to save simulation result")
    file  = open(file_name, "w")
    file.write("sim_count: "+str(count)+" - depl_num: "+str(DEPLOYMENT_NUMBER)+"\n")
    file.write(json.dumps(r))
    file.write("\n\n")
    file.close()
    exit()

#signal.signal(signal.SIGINT, service_shutdown)

previous_simulation = []
def reset_simulation(current_identifier):
    url = "http://%s/simulationreset" % "127.0.0.1:5000"
    r = requests.get(url)
    previous_simulation.append({
        current_identifier: r
    })
    return r.json()

reset_simulation(0)
print("STARTING SIMULATION")

fg = FogDirector("127.0.0.1:5000")
code = fg.authenticate("admin", "admin_123")
if code == 401:
    print("Failed Authentication")

DEVICES_NUMBER = 5
DEPLOYMENT_NUMBER = 10

decision_function = bestFit
for _ in range(0, 10):
    for i in range(0, DEVICES_NUMBER):
        deviceId = i+1      
        _, device1 = fg.add_device("10.10.20."+str(deviceId), "cisco", "cisco")

    # Uploading Application
    code, localapp = fg.add_app("./NettestApp2V1_lxc.tar.gz", publish_on_upload=True)

    for myapp_index in range(0, DEPLOYMENT_NUMBER):
        dep = "dep"+str(myapp_index)
        # Creating myapp1 endpoint
        _, myapp1 = fg.create_myapp(localapp["localAppId"], dep)

        deviceIp = randomFit() #, DEVICES_NUMBER)
        while deviceIp == None:
            deviceIp = randomFit() #, DEVICES_NUMBER)
        code, res = fg.install_app(dep, [deviceIp], resources={"resources":{"profile":"c1.tiny","cpu":100,"memory":32,"network":[{"interface-name":"eth0","network-name":"iox-bridge0"}]}})
        trial = 0
        while code == 400:
            trial += 1
            if trial == 100:
                print(DEPLOYMENT_NUMBER, "are too high value to deploy")
            print("*** Cannot deploy", dep,"to the building router", deviceIp, ".Try another ***")
            deviceIp = randomFit() #1, DEVICES_NUMBER)
            while deviceIp == None:
                deviceIp = randomFit() #, DEVICES_NUMBER)
            code, res = fg.install_app(dep, [deviceIp], resources={"resources":{"profile":"c1.tiny","cpu":100,"memory":32,"network":[{"interface-name":"eth0","network-name":"iox-bridge0"}]}})
        
        fg.start_app(dep)
    r = requests.get('https://localhost:5000/result/simulationcounter')
    print("DEPLOYED IN ", r.text)
    count = 0
    last_count_alerted = 0
    try:
        managed_apps = []
        while count < 20000:
            count += 1
            _, alerts = fg.get_alerts()
            managed_apps = []
            for alert in alerts["data"]:
                last_count_alerted = count
                if "APP_HEALTH" == alert["simulation_type"]: # No other alerts can be triggered
                    dep = alert["appName"]
                    if dep in managed_apps:
                        continue
                    code, _ = fg.stop_app(dep)
                    code, _ = fg.uninstall_app(dep, alert["ipAddress"])
                    devip =  randomFit()
                    while devip == None:
                        devip = randomFit()
                    code, _ = fg.install_app(dep, [devip]) 
                    while code == 400:
                        devip =  randomFit()
                        if devip == None:
                            continue
                        code, _ = fg.install_app(dep, [devip])
                    code, _ = fg.start_app(dep)
    except KeyboardInterrupt:
        r = input("Exit (y/n)?")
        if r == "y":
            service_shutdown()
            exit()

    r = reset_simulation("sim_count:"+str(count)+":depl_num:"+str(DEPLOYMENT_NUMBER))
    file  = open("simulation_result.txt", "a")
    file.write("sim_count: "+str(count)+" - depl_num: "+str(DEPLOYMENT_NUMBER)+"\n")
    file.write(json.dumps(r))
    file.write("\n\n")
    file.close()

file  = open("final_simulation_result.txt", "w")
file.write(json.dumps(previous_simulation))
file.close()

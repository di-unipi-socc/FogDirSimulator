from threading import Thread, Event, Lock
import time, random
from collections import defaultdict
import array
import Database as db
from Simulator.ResourceSampling import sampleCPU, sampleMEM, get_truncated_normal
from constants import queue, SAMPLE_INTERVAL, current_infrastructure, twoarray
from config import profile_low, profile_normal, profile_high, getEnergyConsumed
import constants

iter_count = 0
device_lock = Lock()
myapp_lock = Lock()
itercount_lock = Lock()

def new_device_array():
    return array.array("f", [0, 0, 0, 0, 0, 0, 0, 0])

devices_samples = defaultdict(new_device_array)

sampled_devices = []

# Access position
DEVICE_CRITICAL_CPU_counter_sum = 0
DEVICE_CRITICAL_MEM_counter_sum = 1
NUMBER_OF_MYAPP_ON_DEVICE_counter_sum = 2
DEVICE_CPU_USED_sum = 3
DEVICE_MEM_USED_sum = 4
DEVICE_DOWN_counter_sum = 5
resources_sampled_count = 6
DEVICE_ENERGY_CONSUMPTION_sum = 7

MYAPP_UP_counter = {}
MYAPP_DOWN_counter = {}
MYAPP_CPU_CONSUMING_counter = {}
MYAPP_MEM_CONSUMING_counter = {}
MYAPP_LIFETIME = {}
MYAPP_ON_DEVICE_counter = {}

MYAPP_DEVICE_START_counter = {}
MYAPP_ALERT_counter = {}
MYAPP_ALERT_incrementing = {}
DEVICE_USAGE_RESOURCES_SAMPLED_incrementing = {}

def reset_simulation_counters():
    global MYAPP_UP_counter
    MYAPP_UP_counter = {}
    global MYAPP_DOWN_counter
    MYAPP_DOWN_counter = {}
    global MYAPP_CPU_CONSUMING_counter
    MYAPP_CPU_CONSUMING_counter = {}
    global MYAPP_MEM_CONSUMING_counter
    MYAPP_MEM_CONSUMING_counter = {}
    global MYAPP_LIFETIME
    MYAPP_LIFETIME = {}
    global MYAPP_ON_DEVICE_counter
    MYAPP_ON_DEVICE_counter = {}
    global MYAPP_DEVICE_START_counter
    MYAPP_DEVICE_START_counter = {}
    global MYAPP_ALERT_counter
    MYAPP_ALERT_counter = {}
    global iter_count
    iter_count = 0
    global MYAPP_ALERT_incrementing
    MYAPP_ALERT_incrementing = {}
    global DEVICE_USAGE_RESOURCES_SAMPLED_incrementing
    DEVICE_USAGE_RESOURCES_SAMPLED_incrementing = {}
    global current_infrastructure
    current_infrastructure = defaultdict(twoarray)

myapp_ondevice_already_sampled = {}
def resources_requested(sourceAppName):
    localapp_details = db.getLocalApplicationBySourceName(sourceAppName)
    profile = localapp_details["descriptor"]["app"]["resources"]["profile"]
    if "custom" == profile:
        return (localapp_details["app"]["resources"]["cpu"], localapp_details["app"]["resources"]["memory"])
    elif "c1.tiny" == profile:
        return (100, 32)
    elif "c1.small" == profile:
        return (200, 64)
    elif "c1.medium" == profile:
        return (400, 128)
    elif "c1.large" == profile:
        return (600, 256)
    elif "c1.xlarge" == profile:
        return (1200, 512)
    return (200, 64)

def get_profile_values(profile):
    if profile == constants.MYAPP_PROFILE_HIGH:
        return profile_high
    elif profile == constants.MYAPP_PROFILE_LOW:
        return profile_low
    else:
        return profile_normal

class SimThread(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.shutdown_flag = Event()
    def run(self):
        global iter_count
        global current_infrastructure
        global DEVICE_USAGE_RESOURCES_SAMPLED_incrementing
        
        while not self.shutdown_flag.is_set():
            with itercount_lock:
                iter_count += 1
            with device_lock:
                for dev in db.getDevices():
                    deviceId = dev["deviceId"]
                    if not deviceId in sampled_devices:
                        sampled_devices.append(deviceId)
                        # If new devices, sample probability even if not in run for sampling
                        sampled_free_cpu = sampleCPU(deviceId) - dev["usedCPU"] 
                        sampled_free_mem = sampleMEM(deviceId) - dev["usedMEM"]
                        current_infrastructure[deviceId][0] = sampled_free_cpu
                        current_infrastructure[deviceId][1] = sampled_free_mem
                    
                    r = random.random()
                    if dev["alive"] and r <= dev["chaos_down_prob"]:
                        db.setDeviceDown(deviceId)
                    if not dev["alive"] and r <= dev["chaos_revive_prob"]:
                        db.setDeviceAlive(deviceId)  

                    if dev["alive"]:
                        if iter_count % SAMPLE_INTERVAL == 0:
                            sampled_free_cpu = sampleCPU(deviceId) - dev["usedCPU"] 
                            sampled_free_mem = sampleMEM(deviceId) - dev["usedMEM"]
                            current_infrastructure[deviceId][0] = sampled_free_cpu
                            current_infrastructure[deviceId][1] = sampled_free_mem
                        
                        # adding critical CPU, MEM
                        if sampled_free_cpu <= 0:
                            devices_samples[deviceId][DEVICE_CRITICAL_CPU_counter_sum] += 1
                        if sampled_free_mem <= 0:
                            devices_samples[deviceId][DEVICE_CRITICAL_MEM_counter_sum] += 1
                        # adding sampled resources
                        usedCPU = dev["usedCPU"] if not deviceId in DEVICE_USAGE_RESOURCES_SAMPLED_incrementing else DEVICE_USAGE_RESOURCES_SAMPLED_incrementing[deviceId]["cpu"]
                        usedMEM = dev["usedMEM"] if not deviceId in DEVICE_USAGE_RESOURCES_SAMPLED_incrementing else DEVICE_USAGE_RESOURCES_SAMPLED_incrementing[deviceId]["mem"]
                        device_cpu_used = usedCPU + dev["totalCPU"] - sampled_free_cpu
                        device_mem_used = usedMEM + dev["totalMEM"] - sampled_free_mem

                        devices_samples[deviceId][DEVICE_CPU_USED_sum] += device_cpu_used if device_cpu_used <= dev["totalCPU"] else dev["totalCPU"] 
                        devices_samples[deviceId][DEVICE_MEM_USED_sum] += device_mem_used if device_mem_used <= dev["totalMEM"] else dev["totalMEM"]
                        
                        basal_cpu_usage = dev["totalCPU"] - sampled_free_cpu
                        basal_mem_usage = dev["totalMEM"] - sampled_free_mem
                        consumed_energy = (getEnergyConsumed(deviceId, device_cpu_used, device_mem_used) - 
                                            getEnergyConsumed(deviceId, basal_cpu_usage, basal_mem_usage))
                        devices_samples[deviceId][DEVICE_ENERGY_CONSUMPTION_sum] += consumed_energy
            
                        # adding number of installed apps
                        devices_samples[deviceId][NUMBER_OF_MYAPP_ON_DEVICE_counter_sum] += len(dev["installedApps"])    
                        devices_samples[deviceId][resources_sampled_count] += 1        
                    else: 
                        devices_samples[deviceId][DEVICE_DOWN_counter_sum] += 1
                
            with myapp_lock:
                db.deleteFromSamplingAlerts() # Cleaning all alerts inserted in previous simulation iter
                myapp_jobs_up_counter = {}
                myapp_jobs_down_counter = {}
                DEVICE_USAGE_RESOURCES_SAMPLED_incrementing = {}
                for job in db.getJobs():
                    myappId = job["myappId"]
                    
                    if not myappId in MYAPP_ON_DEVICE_counter: # initialize all counters
                        MYAPP_ON_DEVICE_counter[myappId] = {}
                        MYAPP_CPU_CONSUMING_counter[myappId] = {}
                        MYAPP_MEM_CONSUMING_counter[myappId] = {}
                        MYAPP_DEVICE_START_counter[myappId] = {}
                        MYAPP_ALERT_counter[myappId] = {constants.APP_HEALTH: 0, constants.DEVICE_REACHABILITY: 0, 
                                                        constants.MYAPP_CPU_CONSUMING: 0, constants.MYAPP_MEM_CONSUMING: 0}
                        myapp_ondevice_already_sampled[myappId] = {}
                        MYAPP_ALERT_incrementing[myappId] = 0
                    MYAPP_ALERT_incrementing[myappId] += 1 # keeps trace of jobs in order to averaging the alerting counts

                    myapp_details = db.getMyApp(myappId)
                    localapp_resources = resources_requested(myapp_details["sourceAppName"])
                    max_cpu = localapp_resources[0]
                    max_mem = localapp_resources[1]

                    for device in job["payload"]["devices"]:
                        if not device["deviceId"] in MYAPP_ON_DEVICE_counter[myappId]: # Inizializer
                            MYAPP_ON_DEVICE_counter[myappId][device["deviceId"]] = 0
                            MYAPP_DEVICE_START_counter[myappId] [device["deviceId"]] = 0

                        profile_values = get_profile_values(job["profile"])
                        allocated_cpu = device["resourceAsk"]["resources"]["cpu"]
                        allocated_mem = device["resourceAsk"]["resources"]["memory"]
                        application_cpu_sampling = get_truncated_normal(mean=profile_values[0]*max_cpu, sd=profile_values[0]*max_cpu, low=0, upp=allocated_cpu+1).rvs()
                        application_mem_sampling = get_truncated_normal(mean=profile_values[0]*max_mem, sd=profile_values[0]*max_mem, low=0, upp=allocated_mem+1).rvs()
                        
                        if not device["deviceId"] in DEVICE_USAGE_RESOURCES_SAMPLED_incrementing:
                            DEVICE_USAGE_RESOURCES_SAMPLED_incrementing[device["deviceId"]] = {"cpu": 0, "mem": 0}

                        DEVICE_USAGE_RESOURCES_SAMPLED_incrementing[device["deviceId"]]["cpu"] +=  application_cpu_sampling
                        DEVICE_USAGE_RESOURCES_SAMPLED_incrementing[device["deviceId"]]["mem"] +=  application_mem_sampling

                        device_details = db.getDevice(device["deviceId"])
                        if device_details == None: # the devices is removed without deleting the application
                            continue

                        if ((device["deviceId"] in myapp_ondevice_already_sampled[myappId] and myapp_ondevice_already_sampled[myappId][device["deviceId"]] < iter_count)
                            or (not device["deviceId"] in myapp_ondevice_already_sampled[myappId])):
                            MYAPP_ON_DEVICE_counter[myappId][device["deviceId"]] += 1
                            if job["status"] == "start": 
                                MYAPP_DEVICE_START_counter[myappId][device["deviceId"]] += 1
                            myapp_ondevice_already_sampled[myappId][device["deviceId"]] = iter_count

                        if not db.deviceIsAlive(device["deviceId"]):
                            if not myappId in myapp_jobs_down_counter:
                                myapp_jobs_down_counter[myappId] = 1
                            else:
                                myapp_jobs_down_counter[myappId] += 1
                            db.addAlert({
                                "deviceId": device["deviceId"],
                                "ipAddress": device_details["ipAddress"],
                                "hostname": device_details["ipAddress"],
                                "appName": myapp_details["name"],
                                "severity": "critical",
                                "type": "status",
                                "message": "The device is not reachable",
                                #"message": "The desired state of the app on this device was \"running\" but the actual state is \"stopped\"",
                                "time": int(iter_count), # Relative
                                "source": "Device periodic report",
                                "action": "",
                                "status": "ACTIVE",
                                "simulation_type": constants.DEVICE_REACHABILITY
                            }, from_sampling=True)
                            MYAPP_ALERT_counter[myappId][constants.DEVICE_REACHABILITY] += 1
                        else:
                            if job["status"] == "start":
                                if not myappId in myapp_jobs_up_counter:
                                    myapp_jobs_up_counter[myappId] = 1
                                else:
                                    myapp_jobs_up_counter[myappId] += 1
                            else:
                                if not myappId in myapp_jobs_down_counter:
                                    myapp_jobs_down_counter[myappId] = 1
                                else:
                                    myapp_jobs_down_counter[myappId] += 1
                            sampled_free_cpu = current_infrastructure[device["deviceId"]][0]
                            sampled_free_mem = current_infrastructure[device["deviceId"]][1]
                            if sampled_free_cpu <= 0 and job["status"] == "start":
                                db.addAlert({
                                    "deviceId": device["deviceId"],
                                    "ipAddress": device_details["ipAddress"],
                                    "hostname": device_details["ipAddress"],
                                    "appName": myapp_details["name"],
                                    "severity": "critical",
                                    "type": constants.APP_HEALTH,
                                    "message": "The node on which this app is installed has critical problem with CPU resource",
                                    #"message": "The desired state of the app on this device was \"running\" but the actual state is \"stopped\"",
                                    "time": int(iter_count), # Relative
                                    "source": "Device periodic report",
                                    "action": "",
                                    "status": "ACTIVE"
                                }, from_sampling=True)
                                MYAPP_ALERT_counter[myappId][constants.APP_HEALTH] += 1
                            if sampled_free_mem <= 0 and job["status"] == "start":
                                myapp_details = db.getMyApp(job["myappId"])
                                db.addAlert({
                                    "deviceId": device["deviceId"],
                                    "ipAddress": device_details["ipAddress"],
                                    "hostname": device_details["ipAddress"],
                                    "appName": myapp_details["name"],
                                    "severity": "critical",
                                    "message": "The node on which this app is installed has critical problem with Memory resource",
                                    #"message": "The desired state of the app on this device was \"running\" but the actual state is \"stopped\"",
                                    "time": int(iter_count), # Relative
                                    "source": "Device periodic report",
                                    "action": "",
                                    "status": "ACTIVE",
                                    "type": constants.APP_HEALTH
                                }, from_sampling=True)
                                MYAPP_ALERT_counter[myappId][constants.APP_HEALTH] += 1
                            if application_cpu_sampling > max_cpu*0.95 and job["status"] == "start":
                                db.addAlert({
                                    "deviceId": device["deviceId"],
                                    "ipAddress": device_details["ipAddress"],
                                    "hostname": device_details["ipAddress"],
                                    "appName": myapp_details["name"],
                                    "severity": "critical",
                                    "message": "Application is consuming more that 95%% of allocated CPU on current devices",
                                    "time": int(iter_count), # Relative
                                    "source": "Device periodic report",
                                    "action": "",
                                    "status": "ACTIVE",
                                    "type": constants.MYAPP_CPU_CONSUMING    
                                }, from_sampling=True)
                                MYAPP_ALERT_counter[myappId][constants.MYAPP_CPU_CONSUMING] += 1
                            if application_mem_sampling > max_mem*0.95 and job["status"] == "start":
                                db.addAlert({
                                    "deviceId": device["deviceId"],
                                    "ipAddress": device_details["ipAddress"],
                                    "hostname": device_details["ipAddress"],
                                    "appName": myapp_details["name"],
                                    "severity": "critical",
                                    "message": "Application is consuming more that 95%% of allocated MEM on current devices",
                                    "time": int(iter_count), # Relative
                                    "source": "Device periodic report",
                                    "action": "",
                                    "status": "ACTIVE",
                                    "type": constants.MYAPP_MEM_CONSUMING
                                }, from_sampling=True)
                                MYAPP_ALERT_counter[myappId][constants.MYAPP_MEM_CONSUMING] += 1

                for myapp in db.getMyApps():
                    myappId = myapp["myappId"]
                    if not myappId in MYAPP_LIFETIME: # Inizializer
                        MYAPP_LIFETIME[myappId] = 0
                        MYAPP_DOWN_counter[myappId] = 0
                        MYAPP_UP_counter[myappId] = 0

                    MYAPP_LIFETIME[myappId] += 1
                    if myapp["minjobs"] == 0: # 0 is assumed to be "all jobs have to be run"
                        if myappId in myapp_jobs_down_counter and myapp_jobs_down_counter[myappId] > 0: # If at least one job in donw
                            MYAPP_DOWN_counter[myappId] += 1
                        elif myappId in myapp_jobs_up_counter and myapp_jobs_up_counter[myappId] > 0:
                            MYAPP_UP_counter[myappId] += 1
                        else: # If there are no instaces running
                            MYAPP_DOWN_counter[myappId] += 1
                    else:
                        try:
                            if myapp["minjobs"] <= myapp_jobs_up_counter[myappId]:
                                MYAPP_UP_counter[myappId] += 1
                            else:
                                MYAPP_DOWN_counter[myappId] += 1
                        except KeyError:
                            MYAPP_DOWN_counter[myappId] += 1
                
            queue.execute_next_task() # Executes a task if present, otherwise returns immediately                   
                        
def getDeviceSampling():
    with device_lock:
        devices = db.getDevices()
        result = []
        fix_iter = float(iter_count)
        for deviceId in sampled_devices:
            dev = db.getDevice(deviceId)
            tmp = {}
            tmp["deviceId"] = deviceId
            tmp["ipAddress"] = dev["ipAddress"]
            tmp["port"] = dev["port"]
            tmp["totalCPU"] = dev["totalCPU"]
            tmp["totalMEM"] = dev["totalMEM"]
            tmp["CRITICAL_CPU_PERCENTAGE"] = devices_samples[deviceId][DEVICE_CRITICAL_CPU_counter_sum] / float(devices_samples[deviceId][resources_sampled_count])
            tmp["CRITICAL_MEM_PERCENTAGE"] = devices_samples[deviceId][DEVICE_CRITICAL_MEM_counter_sum] / float(devices_samples[deviceId][resources_sampled_count])
            tmp["AVERAGE_CPU_USED"] = devices_samples[deviceId][DEVICE_CPU_USED_sum] / float(devices_samples[deviceId][resources_sampled_count])
            tmp["AVERAGE_MEM_USED"] = devices_samples[deviceId][DEVICE_MEM_USED_sum] / float(devices_samples[deviceId][resources_sampled_count])
            tmp["AVERAGE_MYAPP_COUNT"] = devices_samples[deviceId][NUMBER_OF_MYAPP_ON_DEVICE_counter_sum] / float(devices_samples[deviceId][resources_sampled_count])
            tmp["DEVICE_DOWN_PROB_chaos"] = devices_samples[deviceId][DEVICE_DOWN_counter_sum] / fix_iter 
            tmp["DEVICE_ENERGY_CONSUMPTION"] = (devices_samples[deviceId][DEVICE_ENERGY_CONSUMPTION_sum] / float(devices_samples[deviceId][resources_sampled_count]))*0.72 # 720/1000 = hours months / Kilo
            result.append(tmp)
    return result

def getMyAppsSampling():
    with myapp_lock:
        myapps = db.getMyApps()
        result = []
        fix_iter = float(iter_count)
        for myapp in myapps:
            myappId = myapp["myappId"]
            tmp = {}
            tmp["myappId"] = myappId
            tmp["name"] = myapp["name"]
            if myappId in MYAPP_UP_counter:
                tmp["UP_PERCENTAGE"] = MYAPP_UP_counter[myappId] / float(MYAPP_LIFETIME[myappId])
            else:
                tmp["UP_PERCENTAGE"] = 0
            if myappId in MYAPP_DOWN_counter:
                tmp["DOWN_PERCENTAGE"] = MYAPP_DOWN_counter[myappId] / float(MYAPP_LIFETIME[myappId])
            else: 
                tmp["DOWN_PERCENTAGE"] = 0
            if myappId in MYAPP_ON_DEVICE_counter:
                tmp["ON_DEVICE_PERCENTAGE"] = {k: (v / float(MYAPP_LIFETIME[myappId])) 
                                                    for k,v in MYAPP_ON_DEVICE_counter[myappId].items()}
                tmp["ON_DEVICE_START_TIME"] = {k: (v/float(MYAPP_LIFETIME[myappId]))
                                                    for k,v in MYAPP_DEVICE_START_counter[myappId].items()}
            else:
                tmp["ON_DEVICE_PERCENTAGE"] = {}
            if myappId in MYAPP_ALERT_counter:
                tmp["ALERT_PERCENTAGE"] = {constants.MYAPP_CPU_CONSUMING: MYAPP_ALERT_counter[myappId][constants.MYAPP_CPU_CONSUMING] / MYAPP_ALERT_incrementing[myappId],
                                            constants.MYAPP_MEM_CONSUMING: MYAPP_ALERT_counter[myappId][constants.MYAPP_MEM_CONSUMING] / MYAPP_ALERT_incrementing[myappId],
                                            constants.APP_HEALTH: MYAPP_ALERT_counter[myappId][constants.APP_HEALTH] / (MYAPP_ALERT_incrementing[myappId]*2),
                                            constants.DEVICE_REACHABILITY: MYAPP_ALERT_counter[myappId][constants.DEVICE_REACHABILITY] / MYAPP_ALERT_incrementing[myappId]}
            else:
                tmp["ALERT_PERCENTAGE"] = {}
            result.append(tmp)
    return result

def getSimulationCount():
    with itercount_lock:
        return iter_count

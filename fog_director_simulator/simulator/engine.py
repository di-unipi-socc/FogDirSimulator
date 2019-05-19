import sys
from argparse import ArgumentParser
from argparse import ArgumentTypeError
from sys import maxsize
from time import sleep
from typing import Callable
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Union

from sqlalchemy.orm.exc import NoResultFound

from fog_director_simulator import database
from fog_director_simulator.database import Config
from fog_director_simulator.database import DatabaseLogic
from fog_director_simulator.database import Device
from fog_director_simulator.database.models import Alert
from fog_director_simulator.database.models import AlertType
from fog_director_simulator.database.models import DeviceMetric
from fog_director_simulator.database.models import DeviceMetricType
from fog_director_simulator.database.models import DeviceSampling
from fog_director_simulator.database.models import Job
from fog_director_simulator.database.models import JobMetric
from fog_director_simulator.database.models import JobMetricType
from fog_director_simulator.database.models import JobStatus
from fog_director_simulator.database.models import MyApp
from fog_director_simulator.database.models import MyAppAlertStatistic
from fog_director_simulator.database.models import MyAppMetric
from fog_director_simulator.database.models import MyAppMetricType
from fog_director_simulator.metrics_collector import device
from fog_director_simulator.metrics_collector import job
from fog_director_simulator.metrics_collector import my_app


def positive_int(value: str) -> int:
    ivalue = int(value)
    if ivalue <= 0:
        raise ArgumentTypeError("%s is an invalid positive int value" % value)
    return ivalue


def _send_alert(db_logic: DatabaseLogic, iterationCount: int, job: Job, device: Device, alert_type: AlertType) -> None:
    try:
        my_app_statistics = db_logic.get_my_app_alert_statistics(myApp=job.myApp, alert_type=alert_type)
    except NoResultFound:
        my_app_statistics = MyAppAlertStatistic(  # type: ignore
            myApp=job.myApp,
            type=alert_type,
            count=0,
        )
    my_app_statistics.count += 1
    alerts_to_create: List[Union[MyAppAlertStatistic, Alert]] = [my_app_statistics]

    if alert_type != AlertType.NO_ALERT:
        alerts_to_create.append(
            Alert(  # type: ignore
                myApp=job.myApp,
                device=device,
                type=alert_type,
                time=iterationCount,
            ),
        )

    db_logic.create(*alerts_to_create)


def _alert_not_alive_device(send_alert: Callable[[AlertType], None]) -> bool:
    send_alert(AlertType.DEVICE_REACHABILITY)

    return True


def _maybe_alert_alive_device(
    send_alert: Callable[[AlertType], None],
    job_metrics: Dict[JobMetricType, JobMetric],
    device: Device,
    device_metrics: Dict[DeviceMetricType, DeviceMetric],
) -> bool:

    # TODO: is this correct?
    if device.reservedCPU > device_metrics[DeviceMetricType.CPU].value:
        send_alert(AlertType.APP_HEALTH)
        return True

    if not job_metrics[JobMetricType.ENOUGH_CPU].value:
        send_alert(AlertType.CPU_CRITICAL_CONSUMPTION)
        return True

    # TODO: is this correct?
    if device.reservedMEM > device_metrics[DeviceMetricType.MEM].value:
        send_alert(AlertType.APP_HEALTH)
        return True

    if not job_metrics[JobMetricType.ENOUGH_MEM].value:
        send_alert(AlertType.MEM_CRITICAL_CONSUMPTION)
        return True

    return False


class Simulator:

    def __init__(self, database_config: database.Config, max_simulation_iterations: Optional[int], verbose: bool):
        self.database_logic = database.DatabaseClient(database_config).logic
        self.iteration_count = 0
        self.max_simulation_iterations = max_simulation_iterations or (maxsize - 1)
        self.verbose = verbose

    def _evaluate_device_metrics(self) -> Dict[Device, Dict[DeviceMetricType, DeviceMetric]]:
        return {
            current_device: {
                device_metric.metricType: device_metric
                for device_metric in device.collect(
                    iterationCount=self.iteration_count,
                    db_logic=self.database_logic,
                    device_id=current_device.deviceId,
                )
            }
            for current_device in self.database_logic.get_all_devices()
        }

    def _evaluate_job_metrics(self) -> Dict[Job, Dict[JobMetricType, JobMetric]]:
        return {
            current_job: {
                job_metric.metricType: job_metric
                for job_metric in job.collect(
                    iterationCount=self.iteration_count,
                    db_logic=self.database_logic,
                    jobId=current_job.jobId,
                )
            }
            for current_job in self.database_logic.get_all_jobs()
        }

    def _evaluate_my_app_metrics(self) -> Dict[MyApp, Dict[MyAppMetricType, MyAppMetric]]:
        return {
            current_my_apps: {
                my_app_metric.metricType: my_app_metric
                for my_app_metric in my_app.collect(
                    iterationCount=self.iteration_count,
                    db_logic=self.database_logic,
                    myAppId=current_my_apps.myAppId,
                )
            }
            for current_my_apps in self.database_logic.get_all_my_apps()
        }

    def _evaluate_device_sampling(
        self,
        device: Device,
        device_metrics: Mapping[Device, Dict[DeviceMetricType, DeviceMetric]],
        job_metrics: Mapping[Job, Dict[JobMetricType, JobMetric]],
        my_app_metrics: Mapping[MyApp, Dict[MyAppMetricType, MyAppMetric]],
    ) -> DeviceSampling:
        device_lifetime = (device.timeOfRemoval or self.iteration_count) - (device.timeOfCreation or 0)

        cpu_metrics = self.database_logic.get_device_metrics(deviceId=device.deviceId, metricType=DeviceMetricType.CPU)
        mem_metrics = self.database_logic.get_device_metrics(deviceId=device.deviceId, metricType=DeviceMetricType.MEM)
        myapps_metrics = self.database_logic.get_device_metrics(deviceId=device.deviceId, metricType=DeviceMetricType.APPS)

        instants_cpu_critical = sum(
            1
            for metric in cpu_metrics
            if metric.value >= 0.95 * device.totalCPU
        )
        instants_mem_critical = sum(
            1
            for metric in mem_metrics
            if metric.value >= 0.95 * device.totalMEM
        )

        used_cpu_ticks = sum(metric.value for metric in cpu_metrics)
        used_mem_ticks = sum(metric.value for metric in mem_metrics)

        installed_my_apps_instants = sum(metric.value for metric in myapps_metrics)

        return DeviceSampling(
            iterationCount=self.iteration_count,
            deviceId=device.deviceId,
            criticalCpuPercentage=instants_cpu_critical / device_lifetime,
            criticalMemPercentage=instants_mem_critical / device_lifetime,
            averageCpuUsed=used_cpu_ticks / device_lifetime,
            averageMemUsed=used_mem_ticks / device_lifetime,
            averageMyAppCount=installed_my_apps_instants / device_lifetime,
        )

    def _evaluate_samplings(
        self,
        device_metrics: Mapping[Device, Dict[DeviceMetricType, DeviceMetric]],
        job_metrics: Mapping[Job, Dict[JobMetricType, JobMetric]],
        my_app_metrics: Mapping[MyApp, Dict[MyAppMetricType, MyAppMetric]],
    ) -> Dict[Device, DeviceSampling]:
        metrics = {
            iteration_device: self._evaluate_device_sampling(
                device=iteration_device,
                device_metrics=device_metrics,
                job_metrics=job_metrics,
                my_app_metrics=my_app_metrics,
            )
            for iteration_device in device_metrics
        }
        # Save all the metrics on the db

        self.database_logic.create(*[metric for metric in metrics.values()])

        return metrics

    def _handle_alerts(
        self,
        device_metrics: Mapping[Device, Dict[DeviceMetricType, DeviceMetric]],
        job_metrics: Mapping[Job, Dict[JobMetricType, JobMetric]],
        my_app_metrics: Mapping[MyApp, Dict[MyAppMetricType, MyAppMetric]],
    ) -> None:
        for current_job, current_job_metrics in job_metrics.items():
            if current_job.status is not JobStatus.START:
                continue

            for current_job_device_allocation in current_job.job_device_allocations:  # type: ignore
                current_job = current_job_device_allocation.job
                current_device = current_job_device_allocation.device

                def send_alert(alert_type: AlertType) -> None:
                    _send_alert(
                        db_logic=self.database_logic,
                        iterationCount=self.iteration_count,
                        job=current_job,
                        device=current_device,
                        alert_type=alert_type,
                    )

                if current_device.isAlive:
                    created_alert = _maybe_alert_alive_device(
                        send_alert=send_alert,
                        job_metrics=current_job_metrics,
                        device=current_device,
                        device_metrics=device_metrics[current_device],
                    )
                else:
                    created_alert = _alert_not_alive_device(send_alert=send_alert)

                if not created_alert:
                    send_alert(AlertType.NO_ALERT)

    @classmethod
    def get_instance(cls, argv: Optional[List[str]] = None) -> 'Simulator':
        parser = ArgumentParser(cls.__doc__)
        parser.add_argument(
            '--max-simulation-iterations',
            dest='max_simulation_iterations',
            type=positive_int,
        )
        parser.add_argument(
            '--verbose',
            dest='verbose',
            action='store_true',
        )
        args = parser.parse_args(args=argv)
        return cls(
            database_config=Config.from_environment(),
            max_simulation_iterations=args.max_simulation_iterations,
            verbose=args.verbose,
        )

    def run(self) -> None:
        while self.iteration_count < self.max_simulation_iterations:
            with self.database_logic:
                self.iteration_count += 1
                print(f'Iteration {self.iteration_count}/{self.max_simulation_iterations}', file=sys.stderr)

                device_metrics = self._evaluate_device_metrics()
                job_metrics = self._evaluate_job_metrics()
                my_app_metrics = self._evaluate_my_app_metrics()

                # Evaluate pre-aggregated metrics to simplify front-end efforts
                # for data retrieval (no need to run a lot of queries all the time)
                # and to provide information about the current state of the simulation
                # (NOTE: this is an hack ... but we're ok-ish for now with this)
                self._evaluate_samplings(
                    device_metrics=device_metrics,
                    job_metrics=job_metrics,
                    my_app_metrics=my_app_metrics,
                )

                self._handle_alerts(
                    device_metrics=device_metrics,
                    job_metrics=job_metrics,
                    my_app_metrics=my_app_metrics,
                )

                self.database_logic.register_simulation_time(self.iteration_count)
                # FIXME: Update device status ... if the device is dead ... what has to be done on the db?

        while True:
            with self.database_logic:
                self.iteration_count += 1
                self.database_logic.register_simulation_time(self.iteration_count)
                sleep(0.1)


if __name__ == '__main__':
    instance = Simulator.get_instance()
    instance.run()

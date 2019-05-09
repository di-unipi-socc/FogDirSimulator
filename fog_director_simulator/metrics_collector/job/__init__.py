from typing import List

from fog_director_simulator.database import DatabaseLogic
from fog_director_simulator.database.models import JobIntensivity
from fog_director_simulator.database.models import JobMetric
from fog_director_simulator.metrics_collector import random_sample
from fog_director_simulator.metrics_collector.job import enough_cpu
from fog_director_simulator.metrics_collector.job import enough_memory
from fog_director_simulator.metrics_collector.job import up_status


_MEAN_FOR_JOB_INTENSIVITY = {
    JobIntensivity.QUIET: 0.5,
    JobIntensivity.NORMAL: 0.7,
    JobIntensivity.HEAVY: 0.9,
}

_STD_DEVIATION_FOR_JOB_INTENSIVITY = {
    JobIntensivity.QUIET: 0.05,
    JobIntensivity.NORMAL: 0.07,
    JobIntensivity.HEAVY: 0.1,
}


def scaled_random_sample(job_intensivity: JobIntensivity, scale_factor: float, upper_bound: float) -> float:
    return random_sample(
        mean=scale_factor * _MEAN_FOR_JOB_INTENSIVITY[job_intensivity],
        std_deviation=scale_factor * _STD_DEVIATION_FOR_JOB_INTENSIVITY[job_intensivity],
        lower_bound=0,
        upper_bound=upper_bound,
    )


def collect(db_logic: DatabaseLogic, iterationCount: int, jobId: int) -> List[JobMetric]:
    result = [
        JobMetric(  # type: ignore
            iterationCount=iterationCount,
            jobId=jobId,
            metricType=enough_cpu.METRIC_TYPE,  # type: ignore
            value=enough_cpu.collect(db_logic=db_logic, job_id=jobId),  # type: ignore
        ),
        JobMetric(  # type: ignore
            iterationCount=iterationCount,
            jobId=jobId,
            metricType=enough_memory.METRIC_TYPE,  # type: ignore
            value=enough_memory.collect(db_logic=db_logic, job_id=jobId),  # type: ignore
        ),
        JobMetric(  # type: ignore
            iterationCount=iterationCount,
            jobId=jobId,
            metricType=up_status.METRIC_TYPE,  # type: ignore
            value=up_status.collect(db_logic=db_logic, job_id=jobId),  # type: ignore
        ),
    ]
    db_logic.create(*result)

    return result

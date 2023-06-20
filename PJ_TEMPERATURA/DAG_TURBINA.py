###############################################################
#       IMPORTS
###############################################################
from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.operators.python_operator import BranchPythonOperator
from airflow.operators.email_operator import EmailOperator
from airflow.sensors.filesystem import FileSensor
from airflow.providers.postgres.operators.postgres import PostgresOperator
#from airflow.operators.postgres_operator import PostgresOperator
from airflow.models import Variable
from airflow.utils.task_group import TaskGroup
from datetime import datetime, timedelta
import json
import os

###############################################################
#       ARGS - FUNCOES
###############################################################
default_args = {
        'depends_on_past':False,
        'email':['hugo.tomita@gmail.com'],
        'email_on_failure' : True,
        'email_on_retry' : False,
        'retries' : 1,
        'retry_delay' : timedelta(seconds=10)
        }


def process_file(**kwargs):
    with open(Variable.get('path_file')) as var_file:
        data=json.load(var_file)
        kwargs['ti'].xcom_push(key='idtemp',value=data['idtemp']) #ti = task instance, criando um xcom para pegar cada valor do arquivo
        kwargs['ti'].xcom_push(key='powerfactor',value=data['powerfactor'])
        kwargs['ti'].xcom_push(key='hydraulicpressure',value=data['hydraulicpressure'])
        kwargs['ti'].xcom_push(key='temperature',value=data['temperature'])
        kwargs['ti'].xcom_push(key='timestamp',value=data['timestamp'])
        os.remove(Variable.get('path_file')) # apagando o arquivo lido

def avalia_temp(**context):
    number = float(context['ti'].xcom_pull(task_ids='get_data', key='temperature'))
    if number >=24:
        return 'group_check_temp.send_email_alert'
    else:
        return 'group_check_temp.send_email_normal'

###############################################################
#       DAG
###############################################################
dag = DAG('DAG_TURBINA', description='pj de teste',
        schedule_interval=None,
        start_date=datetime(2023,6,18),
        catchup=False, # para nao executar as datas do passado.
        default_args=default_args, #carregando da funcao criado acima
        default_view='graph',
        doc_md="## DAG DE CARGA TURBINA!!!!")
###############################################################
#       GROUP
###############################################################
group_check_temp = TaskGroup('group_check_temp', dag=dag) #Criando o grupo de tasks a serem utulizada.
group_database = TaskGroup('group_database', dag=dag) #Criando o grupo de tasks a serem utulizada.

###############################################################
#       TASK para verificar o arquivo
###############################################################
file_sensor_task = FileSensor(
                            task_id='file_sensor_task',
                            filepath= Variable.get('path_file'), # Criado na console - variable
                            fs_conn_id='fs_default',# Criado na console - connection
                            poke_interval = 10,
                            dag=dag)
###############################################################
#       TASK PROCESSAR OS ARUQIVOS
###############################################################

get_data=PythonOperator(
        task_id='get_data',
        python_callable=process_file, # Chamada da funcao
        provide_context=True, # iremos receber contexto
        dag=dag
)
###############################################################
#       TASKs do grupo GROUP_DATABASE
###############################################################

create_table=PostgresOperator(task_id='create_table',
                              postgres_conn_id='postgres', # Criado na console - connection
                              sql=''' create table if not exists 
                              sensors (idtemp varchar,powerfactor varchar,
                              hydraulicpressure varchar,temperature varchar,
                              timestamp varchar); ''',# utilizado 3 aspas simples para quebrar linha
                              task_group = group_database, # atribuindo a task ao grupo
                              dag=dag
                              )
insert_data=PostgresOperator(task_id='insert_data',
                            postgres_conn_id='postgres',# Criado na console - connection
                            parameters=(
                                        '{{ ti.xcom_pull(task_ids="get_data",keys="idtemp") }}',
                                        '{{ ti.xcom_pull(task_ids="get_data",keys="powerfactor") }}',
                                        '{{ ti.xcom_pull(task_ids="get_data",keys="hydraulicpressure") }}',
                                        '{{ ti.xcom_pull(task_ids="get_data",keys="temperature") }}',
                                        '{{ ti.xcom_pull(task_ids="get_data",keys="timestamp") }}'
                                        ), # Usado no parametro paramters o jinja...
                            sql='''INSERT INTO sensors 
                                        (idtemp ,powerfactor ,hydraulicpressure ,temperature ,timestamp ) 
                                        VALUES (%s,%s,%s,%s,%s);''',
                            task_group = group_database,
                            dag=dag
                            )
###############################################################
#       TASKs do grupo GROUP_CHECK
###############################################################

send_email_alert=EmailOperator(
                                task_id = 'send_email_alert',
                                to='hugo.tomita@gmail.com',
                                subject='Airflow alerta',
                                html_content=''' <h3> ALERTA TEMPERATURA. </h3>
                                <p>DAG: turbina </p>''',
                                task_group=group_check_temp,
                                dag=dag
                                )

send_email_normal=EmailOperator(
                                task_id = 'send_email_normal',
                                to='hugo.tomita@gmail.com',
                                subject='Airflow normal',
                                html_content=''' <h3>  NORMAL TEMPERATURA. </h3>
                                <p>DAG: turbina </p>''',
                                task_group=group_check_temp,
                                dag=dag
                                )
    
check_temp_branch=BranchPythonOperator(
                                task_id = 'check_temp_branch',
                                python_callable=avalia_temp,
                                provide_context=True,
                                task_group=group_check_temp,
                                dag=dag
                                )


with group_check_temp:
    check_temp_branch >> [send_email_alert,send_email_normal]

with group_database:
    create_table >> insert_data

file_sensor_task >> get_data
get_data >> [group_check_temp,group_database]

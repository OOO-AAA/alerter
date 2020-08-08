import psycopg2
import psycopg2.extras
import sqlite3
import os

import management


#   Класс представляет собой абстракцию для работы с базой данных.
#
#   Желательно с классом работать изнутри этого модуля. Целевая схема следующая:
#
#       создается функция, которая будет вызываться извне, def function
#       внутри функции определяется запрос к БД
#     
#       db = db_connection()    // создается экземпляр класса
#       db.open()               // открывается подклчюение
#       result = db.execute...  // выполняется запрос
#       db.close()              // закрывается подключение
#
#   Методы класса
#       
#       open                создать подключение к БД
#       close               закрыть подключение
#       execute             выполняет запрос и возвращает результат в виде списка словарей
#       execute_scalar      выполняет запрос и возвращает результат в виде одного значения
#                           нужно использовать в запросах типа "select count(x) from" или "select top 1 x from" 
#       execute_non_query   необходимо использовать для запросов, которые изменяют данные "insert", "update"
#       eecute_script       выполняет скрипт из *.sql-файла
#       test_connection     проверить возможность подключения
#                           0 - все в порядке
#                           1 - подключение есть, отсутствует структура, можно вызвать метод create_db
#                           2 - что-то непонятное, нужно искать причины
#
#   Атрибуты класса (извне не используются)
#
#       rdbms               тип БД
#       connection_string   строка подключения
#       connection          текущее подключение


class db_connection:
    def __init__(self):
        self.rdbms, self.db_connection_string, self.debug = management.get_settings(
            ["rdbms", "db_connection_string", "debug"])

    def create_db(self):
        
        self.open()

        # Создание структуры базы данных

        if self.rdbms == "sqlite":
            if os.path.exists(self.db_connection_string):
                os.remove(self.db_connection_string)            
            self.execute_script("cicd/sqlite_create_db.sql")            
        elif self.rdbms == "postgresql":
            self.execute_script("cicd/postgres_create_db.sql")

        # Заполнение таблицы mac_owners  
                  
        with open('cicd/macs.txt', encoding="utf-8") as file:
            lines = file.read().splitlines()
        query = 'insert into mac_owners(mac, manufacturer) values '
        for line in lines:
            mac, owner = line[0:6].replace('\'', '\'\''), line[11:].replace('\'', '\'\'')
            query = query + '(\'' + mac + '\', \'' + owner + '\'),'
        query = query[0:-1] + ';'
        self.execute_non_query(query)

        # Тестовые наборы данных для отладки

        if self.debug:
            self.execute_script("cicd/debug_data.sql")

        self.close()

    def open(self):
        if self.rdbms == "sqlite":
            self.connection = sqlite3.connect(self.db_connection_string)
        elif self.rdbms == "postgresql":
            self.connection = psycopg2.connect(self.db_connection_string)

    def close(self):
        self.connection.close()

    def test_connection(self):
        if self.rdbms == "sqlite":
            if os.path.exists(self.db_connection_string):
                return 0
            else:
                return 1
        elif self.rdbms == "postgresql":
            # проверка доступности базы данных
            try:
                self.open()
                # проверка наличия структуры в базе данных
                query = "select count(table_name) _count from information_schema.tables  WHERE table_schema='public'"
                table_count = self.execute_scalar(query)
                if table_count == 0:
                    self.close()
                    return 1
                else:    
                    self.close()
                    return 0
            except:
                return 2
        return 2

    def dict_factory(self, cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    def execute(self, query):
        if self.rdbms == 'sqlite':
            self.connection.row_factory = self.dict_factory
            cursor = self.connection.cursor()
        elif self.rdbms == 'postgresql':
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute(query)
        result = cursor.fetchall()
        cursor.close()
        return result

    def execute_non_query(self, query):
        cursor = self.connection.cursor()
        cursor.execute(query)
        self.connection.commit()
        cursor.close()
        return True

    def execute_scalar(self, query):
        cursor = self.connection.cursor()
        cursor.execute(query)
        result = cursor.fetchone()[0]
        cursor.close()
        return result

    def execute_script(self, path):
        cursor = self.connection.cursor()
        with open(path, 'r') as file:
            query = file.read().replace('\n', ' ').replace('\t','')
        if self.rdbms == 'sqlite':
            cursor.executescript(query)
        elif self.rdbms == 'postgresql':
            cursor.execute(query)
        self.connection.commit()
        cursor.close()
        return True
        


def get_value(data):
    if data is None:
        value = 'null'
    elif not data.isdigit():
        value = '\'' + data.replace('\'', '\'\'') + '\''
    else:
        value = data
    return value


#
#   Функции для работы извне
#

#   Вставка словаря в соответствующую таблицу
#
#   data    словарь
#   table   имя таблицы
#   conn    подключение
#
#   Если подключение не передается в качестве параметра, то создается подключение по умолчанию, которое закрывается после выполнения

def insert_data(data, table, conn='not_created'):
    columns, values = '', ''
    for key in data:
        if columns == '':
            columns += key
            values += get_value(data[key])
        else:
            columns = columns + ', ' + key
            values = values + ', ' + get_value(data[key])

    query = 'insert into ' + table + '(' + columns + ') values(' + values + ')'

    connection = conn
    if connection == 'not_created':
        db = db_connection()
        db.open()

    db.execute_non_query(query)

    if connection == 'not_created':
        db.close()


#   Проверка существования логина
#
#   login       проверяемый логин

def login_exists(login):
    query = 'select count(1) _count from [admin] where [login] = %(login)s' % {'login': login}
    db = db_connection()
    db.open()
    result = (int(db.execute_scalar(query)) > 0)
    db.close()
    return result


#   Выборка событий из syslog'а
#
#   all_events          получать только c тэгами link-up и LINK_DOWN
#   only_unknown_mac    получить события только с неизвестными mac'ами
#   started_at          начало диапазона
#   ended_at            конец диапазона
#
#   По умолчанию в выборку попадают все события за последний два часа

def get_events(all_events=True, only_unknown_mac=False, started_at='', ended_at=''):

    db = db_connection()

    if db.rdbms == 'sqlite':
        if started_at == '':
            started_at = 'datetime(\'now\',\'-2000 hour\', \'localtime\')'
        if ended_at == '':
            ended_at = 'datetime(\'now\', \'localtime\')'
    elif db.rdbms == 'postgresql':
         if started_at == '':
            started_at = 'current_timestamp + interval \'-2000 hour\''
         if ended_at == '':
            ended_at = 'current_timestamp'       

    query = '''select 
			receivedat,
			priority,
			from_host,
			process,
			syslog_tag,
            case
                when mac_addresses.mac is null then ''
                when mac_addresses.wellknown = 1 then 'wellknown'
                when mac_addresses.mac is not null and (mac_addresses.wellknown is null or mac_addresses.wellknown = 0) then 'unknown'
            end mac_type,
			message,
            syslog.mac
		from
			syslog
            left join
            mac_addresses
            on upper(syslog.mac) = upper(mac_addresses.mac)
		where
			device_time > %(started_at)s
			and
			device_time < %(ended_at)s
		 ''' % {'started_at': started_at, 'ended_at': ended_at}
    if all_events == False:
        query = query + ' and (syslog_tag like \'%link-up%\' or syslog_tag like \'%LINK_DOWN%\')'

    query = query + ''' order by receivedat desc limit 500'''

    db = db_connection()
    db.open()
    result = db.execute(query)
    db.close()

    return result


#   Выборка текущих подключений к сетевому оборудованию
#
#   from_host
#   port
#   mac
#   mac_type
#   manufacturer
#   up_time
#
#   Фильтр
#       only_unknown    только "недоверенные" mac-адресы

def get_current_state(only_unknown=False):
    query = '''select
	            from_host,
	            port,
	            current_state.mac mac,
                case
                    when mac_addresses.mac is null then ''
                    when mac_addresses.wellknown = 1 then 'wellknown'
                    when mac_addresses.mac is not null and (mac_addresses.wellknown is null or mac_addresses.wellknown = 0) then 'unknown'
                end mac_type,
                manufacturer,
	            started_at up_time
            from
	            current_state
	            join
	            mac_addresses 
	            on
	            upper(current_state.mac) = upper(mac_addresses.mac)
	            left join
	            mac_owners
	            on
	            upper(substr(replace(mac_addresses.mac,':',''),1,6)) = mac_owners.mac
            where
	            state = 1
		    '''
    if only_unknown:
        query = query + " and mac_addresses.mac is not null and (mac_addresses.wellknown is null or mac_addresses.wellknown = 0) "

    query = query + "order by from_host, port"

    db = db_connection()
    db.open()
    result = db.execute(query)
    db.close()

    return result


#   Выборка всех доверенных mac-адресов

def get_wellknown_mac():
    query = '''select 
					mac_addresses.mac mac,
					mac_addresses.wellknown_author wellknown_author,
					mac_addresses.description description,
					mac_addresses.wellknown_started_at wellknown_started_at,
					mac_owners.manufacturer manufacturer
				from 
					mac_addresses 
					left join
					mac_owners
					on
					upper(substr(replace(mac_addresses.mac,':',''),1,6)) = mac_owners.mac
				where 
					wellknown = 1
				'''

    db = db_connection()
    db.open()
    result = db.execute(query)
    db.close()

    return result


#   Выборка всех недоверенных mac-адресов

def get_unknown_mac():
    query = '''select 
					mac_addresses.mac mac,
					mac_owners.manufacturer manufacturer
				from 
					mac_addresses 
					left join
					mac_owners
					on
					upper(substr(replace(mac_addresses.mac,':',''),1,6)) = mac_owners.mac
				where 
					wellknown = 0 
					or 
					wellknown is null
				'''

    db = db_connection()
    db.open()
    result = db.execute(query)
    db.close()

    return result


#   Установка признака "доверенный" для mac-адреса

def set_mac_to_wellknown(mac, login, description):
    
    db = db_connection()

    query = '''update
						mac_addresses
					set
						wellknown = 1,
						wellknown_author = '%(login)s',
						description = '%(description)s',
            '''
    if db.rdbms == 'sqlite':
        query = query + '''wellknown_started_at = datetime('now','localtime')'''
    elif db.rdbms == 'postgresql':
        query = query + '''wellknown_started_at = current_timestamp'''

    query = query + ''' where
						mac = '%(mac)s'
					''' % {'login': login, 'mac': mac, 'description': description}
  
    db.open()
    db.execute_non_query(query)
    db.close()


#   Удаление признака "доверенный" для mac-адреса

def set_mac_to_unknown(mac, login):

    db = db_connection()

    query = '''update
						mac_addresses
					set
						wellknown = 0,
						wellknown_author = '%(login)s',
						description = '',
            '''
    if db.rdbms == 'sqlite':
        query = query + '''wellknown_started_at = datetime('now','localtime')'''
    elif db.rdbms == 'postgresql':
        query = query + '''wellknown_started_at = current_timestamp'''

    query = query + ''' where
						mac = '%(mac)s'
					''' % {'login': login, 'mac': mac}

    
    db.open()
    db.execute_non_query(query)
    db.close()


#   Аутентификация

def flask_logon(login, hash):
    query = '''
                select
                    count(1) _count
                from
                    admin
                where
                    login = '%(login)s'
                    and
                    hash = '%(hash)s'
            ''' % {'login': login, 'hash': hash}

    db = db_connection()
    db.open()
    result = (int(db.execute_scalar(query)) > 0)
    db.close()
    return result

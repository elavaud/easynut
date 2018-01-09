# -*- coding: utf-8 -*-
"""
Terminology:
- Table/Column: Used when we talk about DB objects.
- Model/Field: Used when we talk about Python objects.
- Model/Table ID: Unique identifier of a model/table (they both have the same value).
- Field/Column ID: Unique identifier of a field/column (they both have the same value).
- Dynamic model/field: Model/field having its structure defined in the database.
- Non dynamic field: A field that is not dynamic, that is hardcoded in the DB table.
- DynamicRegistry: Centralize operations related to dynamic models stored in the database.
- DynamicModelConfig: Config information of a dynamic model.
- DynamicFieldConfig: Config information of a dynamic field.
- DynamicModel: Simulate a Django Model (i.e. fields and behaviors of the data stored in the database).
- DynamicManager: Simulate a Django Manager (i.e. interface through which database operations are provided to models).
- Data slug: A unique identifier for a ``model.field`` (used in Excel templates).
- Special fields: Dynamic DB columns that have special meaning/usage.
"""
from collections import Iterable, OrderedDict
import re

from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist

from .utils import Cast, DataDb, clean_sql, force_list


# Format of dynamic tables (data and config) and dynamic columns.
DYNAMIC_REGISTRY_DB_CONFIG_TABLE_NAME_FORMAT = "tablas"
DYNAMIC_MODEL_DB_DATA_TABLE_NAME_FORMAT = "tabla_{}"
DYNAMIC_MODEL_DB_CONFIG_TABLE_NAME_FORMAT = "tabla_{}_des"
DYNAMIC_FIELD_DB_COL_NAME_FORMAT = "campo_{}"

# Validation regex for dynamic field DB column names.
RE_DYNAMIC_FIELD_DB_COL_NAME_VALIDATION = re.compile(r"^campo_[0-9]+$")

# DB column names of non dynamic fields.
NON_DYNAMIC_FIELDS_DB_COL_NAMES = ("_id", "user", "timestamp")

# DB column name of the primary key in DB tables ``tabla_X``).
PK_DB_COL_NAME = "_id"

# Verbose names of special fields (cf. DB column ``presentador`` in DB tables ``tabla_X_des``).
MSF_ID_VERBOSE_NAME = "MSF ID"
DATE_VERBOSE_NAME = "Date"

# Data slug format and validation.
DATA_SLUG_SEPARATOR = "#"
DATA_SLUG_FORMAT = "{model_id:02d}#{field_id:02d}"
RE_DATA_SLUG_VALIDATION = re.compile(r"^[0-9]{2}#[0-9]{2}$")


# MODELS ======================================================================

class DynamicManager(object):
    """
    Simulate Django Managers for ``DynamicModel``.

    From Django: A Manager is the interface through which database query operations are provided to Django models.
    """

    def __init__(self, model_config):
        self.model_config = model_config  # The model config registered with this manager.

    def all(self):
        """Return all records."""
        sql = self._build_sql()
        return self._generate_models(sql)

    def filter(self, msf_id):
        """Return all records matching the given MSF ID."""
        where = "{}='{}'".format(self.model_config.msf_id_db_col_name, msf_id)
        sql = self._build_sql(where=where)
        return self._generate_models(sql)

    def get(self, pk=None, msf_id=None):
        """Return a single record matching the pk or MSF ID."""
        # Build the WHERE content (without the actual "WHERE", see ``self._build_sql()``).
        if pk:
            where = "{}={}".format(PK_DB_COL_NAME, pk)
        elif msf_id:
            where = "{}='{}'".format(self.model_config.msf_id_db_col_name, msf_id)
        else:
            raise Exception("You must provide either a pk or MSFID.")

        # Build the SQL statement.
        sql = self._build_sql(where=where)

        # Execute the query.
        with DataDb.execute(sql) as c:
            # Raise an exception if no record found or multiple records found.
            if c.rowcount == 0:
                raise ObjectDoesNotExist()
            if c.rowcount > 1:
                raise MultipleObjectsReturned()

            row = c.fetchone()

        return self._generate_model(row)

    def _build_sql(self, db_cols=["*"], where=None, **kwargs):
        """Build a SQL query based on the given parameters."""
        # Build the WHERE clause.
        where_clause = ""
        if where is not None:
            where_clause = "WHERE {}".format(where)

        # Sort results by MSF ID, then by date if that column exists.
        order_by = [self.model_config.msf_id_db_col_name]
        if self.model_config.date_db_col_name is not None:
            order_by.append("{} DESC".format(self.model_config.date_db_col_name))

        # Build the SQL statement.
        sql = clean_sql("""
            SELECT {cols}
            FROM {table}
            {where_clause}
            ORDER BY {order_by}
        """.format(
            cols=", ".join(force_list(db_cols)),
            table=self.model_config.db_data_table,
            where_clause=where_clause,
            order_by=", ".join(order_by),
        ))
        return sql

    def _generate_model(self, data_row):
        """Generate a model using the given data."""
        return self.model_config.model_factory(data_row=data_row)

    def _generate_models(self, sql):
        """Generate models list using the given SQL query."""
        models = []
        with DataDb.execute(sql) as c:
            for row in c.fetchall():
                models.append(self._generate_model(row))
        return models


class DynamicModel(object):
    """
    Simulate Django Models for dynamic DB tables.

    From Django: A model is the single, definitive source of information about your data. It contains the essential
    fields and behaviors of the data you're storing. Generally, each model maps to a single database table.
    """

    def __init__(self, model_id):
        self.model_id = model_id  # ID of the ``DynamicModelConfig``.

        self._model_config = DynamicRegistry.get_model_config(model_id)  # Link to the ``DynamicModelConfig``.
        self.fields_value = OrderedDict()  # Fields value.
        self.related_models = {}  # Cache of related models.

        # Initialize non dymanic fields to ``None``.
        for db_col_name in NON_DYNAMIC_FIELDS_DB_COL_NAMES:
            setattr(self, db_col_name, None)

    @property
    def pk(self):
        """Convenient access to the DB primary key."""
        return getattr(self, PK_DB_COL_NAME)

    @property
    def msf_id(self):
        """Convenient access to the special field ``MSF ID``."""
        return self.get_field_value(self._model_config.msf_id_field_id)

    @property
    def date(self):
        """Convenient access to the special field ``Date``."""
        return self.get_field_value(self._model_config.date_field_id)

    def get_field_value(self, field_id):
        """Return the value of a field based on its ID."""
        return self.fields_value[field_id]

    def get_field_config(self, field_id):
        """Return the ``DynamicFieldConfig`` of a field based on its ID."""
        return self._model_config.fields_config[field_id]

    def get_related_models(self, model_id):
        """Return related models for the given model ID, loading it if not already available."""
        if model_id not in self.related_models:
            self.load_related_models(model_id)
        return self.related_models[model_id]

    def get_value_from_data_slug(self, data_slug):
        """Return the field value based on a data slug, for this model or a related one."""
        model_id, field_id = DynamicRegistry.split_data_slug(data_slug)
        if model_id == self.model_id:
            return self.get_field_value(field_id)

        related_models = self.get_related_models(model_id)
        return [m.get_field_value(field_id) for m in related_models]

    def load_data(self, data_row):
        """Initialize model fields value based on a DB row."""
        for db_col_name, value in data_row.iteritems():
            if db_col_name in NON_DYNAMIC_FIELDS_DB_COL_NAMES:
                setattr(self, db_col_name, value)
            else:
                field_id = self._model_config.get_field_id_from_db_col_name(db_col_name)
                if field_id in self._model_config.fields_config:
                    self.fields_value[field_id] = value

    def load_related_models(self, model_id):
        """Load data for the same MSF ID from another model."""
        model_config = DynamicRegistry.get_model_config(model_id)
        self.related_models[model_id] = model_config.objects.filter(msf_id=self.msf_id)


# MODELS CONFIG ===============================================================

class DynamicFieldConfig(object):
    """
    Config of a dynamic field, of a dynamic model.

    Config information stored in the ``DYNAMIC_MODEL_DB_CONFIG_TABLE_NAME_FORMAT`` DB table.
    """

    def __init__(self, field_id, model_config, attrs):
        self.id = field_id
        self.model_config = model_config  # Link to the parent ``DynamicModelConfig``.

        # Define field attributes: db_col_name, name, position, kind, values_list,
        #     has_list, has_detail, has_find, has_use, has_new_line, is_editable.
        # Note: Attributes are retrieved in ``DynamicModelConfig._load_fields_config()``.
        for k, v in attrs.iteritems():
            setattr(self, k, v)

    @property
    def data_slug(self):
        return DATA_SLUG_FORMAT.format(model_id=self.model_config.id, field_id=self.id)


class DynamicModelConfig(object):
    """
    Config of a dynamic model.

    Config information stored in the ``DYNAMIC_REGISTRY_DB_CONFIG_TABLE_NAME_FORMAT`` DB table.
    """

    def __init__(self, model_id, attrs, data_row=None):
        self.id = model_id  # Model ID.

        # Define model attributes: name.
        # Note: Attributes are retrieved in ``DynamicRegistry.load_models_config()``.
        for k, v in attrs.iteritems():
            setattr(self, k, v)

        # DB tables containing the model fields config and the data.
        self.db_config_table = DynamicRegistry.get_db_config_table_name(self.id)
        self.db_data_table = DynamicRegistry.get_db_data_table_name(self.id)

        # Field ID of special fields.
        self.msf_id_field_id = None
        self.date_field_id = None

        # Initialize the fields config registry.
        self.fields_config = OrderedDict()
        self._load_fields_config()

        # Create an instance of the manager and register this model config with it.
        self.objects = DynamicManager(self)

        # Load initial data.
        if data_row is not None:
            self._load_data(data_row)

    @property
    def msf_id_db_col_name(self):
        """Convenient access to the DB col name of the special field ``MSF ID``."""
        if self.msf_id_field_id is None:
            return None
        return self.get_field_config(self.msf_id_field_id).db_col_name

    @property
    def date_db_col_name(self):
        """Convenient access to the DB col name of the special field ``Date``."""
        if self.date_field_id is None:
            return None
        return self.get_field_config(self.date_field_id).db_col_name

    def delete(self):
        """Delete this record from DB."""
        raise NotImplemented()  # @TODO

    def get_field_config(self, field_id):
        """Return the config of a field based on its ID."""
        return self.fields_config[field_id]

    def get_field_id_from_db_col_name(self, db_col_name):
        """Return the field ID from its DB column name."""
        # /!\ Dangerous use of ``DYNAMIC_FIELD_DB_COL_NAME_FORMAT``.
        return Cast.int(db_col_name.replace(DYNAMIC_FIELD_DB_COL_NAME_FORMAT.format(""), ""))

    def model_factory(self, data_row=None):
        """Create a dynamic model for this model config, and load data if provided."""
        model = DynamicModel(self.id)
        if data_row is not None:
            model.load_data(data_row)
        return model

    def save(self):
        """Save this record in DB (using an INSERT or UPDATE)."""
        raise NotImplemented()  # @TODO

    def _cast_field_config_row(self, row):
        """Apply data conversion on the given field config values."""
        row["id"] = self.get_field_id_from_db_col_name(row["db_col_name"])
        row["position"] = Cast.int(row["position"])
        row["kind"] = Cast.field_kind(row["kind"])
        row["values_list"] = Cast.csv(row["values_list"])
        row["has_list"] = Cast.bool(row["has_list"])
        row["has_detail"] = Cast.bool(row["has_detail"])
        row["has_find"] = Cast.bool(row["has_find"])
        row["has_use"] = Cast.bool(row["has_use"])
        row["has_new_line"] = Cast.bool(row["has_new_line"])
        row["is_editable"] = Cast.bool(row["is_editable"])

    def _load_fields_config(self):
        """Initialize model fields config."""
        # Build the query to retrieve the fields config.
        sql = clean_sql("""
            SELECT campo_id AS db_col_name,
                presentador AS name,
                pos AS position,
                tipo AS kind,
                varios AS values_list,
                listado AS has_list,
                detalle AS has_detail,
                buscar AS has_find,
                usar AS has_use,
                nuevaLinea AS has_new_line,
                editable AS is_editable
            FROM {table}
            ORDER BY pos
        """.format(table=self.db_config_table))

        # Execute the query.
        with DataDb.execute(sql) as c:
            # If no record found, raise Exception.
            if c.rowcount == 0:
                if ids is None:
                    raise RuntimeError(
                        "No dynamic fields config found in database for this model (ID: {}).".format(self.id)
                    )
                else:
                    raise AttributeError("No dynamic model found matching '{}'.".format(ids))

            # Loop over records.
            for row in c.fetchall():
                # Apply data conversion.
                self._cast_field_config_row(row)
                field_id = row.pop("id")
                # Create an instance of ``DynamicFieldConfig`` and store it in the fields config registry.
                self.fields_config[field_id] = DynamicFieldConfig(field_id, self, row)

                # Register the field ID of special fields.
                if row["name"] == MSF_ID_VERBOSE_NAME:
                    self.msf_id_field_id = field_id
                elif row["name"] == DATE_VERBOSE_NAME:
                    self.date_field_id = field_id


class DynamicRegistry(object):
    """Registry of available dynamic models. This is a ``Singleton``."""
    # Singleton pattern: See right after this class definition for the ``Singleton`` implementation.

    def __init__(self):
        # Initialize the models config registry.
        self.models_config = OrderedDict()

        # Whether all models config have been loaded.
        self._all_models_config_loaded = False

    def build_sql(self, models_fields):
        """Build a SQL query based on the given parameters."""
        # Check that the given config is not empty.
        if len(models_fields) == 0:
            raise Exception("The `models_fields` config is empty.")

        select_cols = []  # Column names for the SELECT clause.
        from_clause = ""  # The whole FROM clause (including the FROM and optional JOINs).

        # The first table in the given config is considered as the main table for JOINs.
        # @TODO: This could be specified in separate method parameters.
        main_table = None
        main_id_col = None

        # Loop over models from the given config.
        for model_id, field_ids in models_fields.iteritems():
            # Retrieve the table name and the name of the ID column.
            table_name = self.get_db_data_table_name(model_id)
            id_col = self.get_msf_id_db_col_name(model_id)  # Use MSF ID as ID column.

            # The first model is the main one, use it for the FROM clause (and register it as the main table).
            if main_table is None:
                from_clause = "FROM {}".format(table_name)
                main_table = table_name
                main_id_col = id_col
            # Use JOINs for other models (using the main table).
            else:
                from_clause += " LEFT JOIN {table} ON {table}.{id_col}={main_table}.{main_id_col}".format(
                    table=table_name, id_col=id_col,
                    main_table=main_table, main_id_col=main_id_col,
                )

            # Loop over fields.
            for field_id in field_ids:
                # Retrieve the column name and the data slug (used as column alias).
                col_name = self.get_db_col_name(field_id)
                data_slug = self.get_data_slug(model_id, field_id)

                # Add the column to the SELECT columns.
                select_cols.append("{}.{} AS `{}`".format(table_name, col_name, data_slug))

        # Build the SQL statement.
        sql = clean_sql("""
            SELECT {cols}
            {from_clause}
            {where_clause}
            ORDER BY {main_table}.{main_id_col}
        """.format(
            cols=", ".join(select_cols),
            from_clause=from_clause,
            main_table=main_table, main_id_col=main_id_col,
        ))
        return sql

    def get_data_slug(self, model_id, field_id):
        """Return the data slug for given model and field IDs."""
        field_config = self.get_field_config(model_id, field_id)
        return field_config.data_slug

    def get_db_col_name(self, field_id):
        """Return the name of the DB column for the given field ID."""
        return DYNAMIC_FIELD_DB_COL_NAME_FORMAT.format(field_id)

    def get_db_config_table_name(self, model_id):
        """Return the name of the DB config table for the given model ID."""
        return DYNAMIC_MODEL_DB_CONFIG_TABLE_NAME_FORMAT.format(model_id)

    def get_db_data_table_name(self, model_id):
        """Return the name of the DB data table for the given model ID."""
        return DYNAMIC_MODEL_DB_DATA_TABLE_NAME_FORMAT.format(model_id)

    def get_field_config(self, model_id, field_id):
        """Get a given dynamic field config."""
        model_config = self.get_model_config(model_id)
        return model_config.get_field_config(field_id)

    def get_model(self, model_id, **kwargs):
        """Get a dynamic model populated with its data."""
        model_config = DynamicRegistry.get_model_config(model_id)
        return model_config.objects.get(**kwargs)

    def get_model_config(self, model_id):
        """Return the model config for the given model ID, loading it if not already available."""
        if model_id not in self.models_config:
            self.load_models_config(model_id)
        return self.models_config[model_id]

    def get_msf_id_db_col_name(self, model_id):
        """Return the DB col name of the special field ``MSF ID`` for the given model ID."""
        model_config = self.get_model_config(model_id)
        return model_config.msf_id_db_col_name

    def get_date_db_col_name(self, model_id):
        """Return the DB col name of the special field ``Date`` for the given model ID."""
        model_config = self.get_model_config(model_id)
        return model_config.date_db_col_name

    def load_models_config(self, ids=None):
        """Initialize all available dynamic models config, or given ones."""
        # Don't reload all models config if it has already been done.
        if ids is None and self._all_models_config_loaded:
            return

        # Build the SQL statement.
        sql = clean_sql("""
            SELECT CAST(tabla_id AS UNSIGNED) AS id, presentador AS name
            FROM tablas
            {where_clause}
            ORDER BY id
        """.format(where_clause=self._build_models_config_where_clause(ids)))

        # Execute the query.
        with DataDb.execute(sql) as c:
            # Raise an exception if no record found.
            if c.rowcount == 0:
                if ids is None:
                    raise RuntimeError("No dynamic models found in database.")
                else:
                    raise AttributeError("No dynamic model found matching IDs '{}'.".format(ids))

            # Loop over records.
            for row in c.fetchall():
                # Apply data conversion.
                self._cast_model_config_row(row)

                # Create an instance of ``DynamicModelConfig`` and store it in the models config registry.
                model_id = row.pop("id")
                self.models_config[model_id] = DynamicModelConfig(model_id, row)

        # Register all models config as loaded.
        if ids is None:
            self._all_models_config_loaded = True

    def split_data_slug(self, data_slug):
        """Split the data slug into ``(model_id, field_id)``."""
        return [int(v) for v in data_slug.split(DATA_SLUG_SEPARATOR)]

    def _build_models_config_where_clause(self, ids):
        """Build the WHERE clause to retrieve dynamic models config as requested."""
        if ids is None:
            return ""

        where = "WHERE CAST(tabla_id AS UNSIGNED)"
        if isinstance(ids, Iterable):
            where += " IN ({})".format(", ".join(ids))
        else:
            where += " = {}".format(ids)

        return where

    def _cast_model_config_row(self, row):
        """Apply data conversion on the given model config."""
        row["id"] = Cast.int(row["id"])


# Singleton: Override class with its instance.
DynamicRegistry = DynamicRegistry()

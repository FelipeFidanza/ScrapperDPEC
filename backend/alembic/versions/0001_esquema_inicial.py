"""Esquema inicial.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_MOMENTO = sa.DateTime(timezone=True)
_TABLAS = ("cortes", "corte_dias", "zonas", "suscripciones", "notificaciones")


def upgrade() -> None:
    op.create_table(
        "cortes",
        sa.Column("articulo_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("titulo", sa.String(), nullable=False),
        sa.Column("enlace", sa.String(), nullable=False),
        sa.Column("publicado_en", _MOMENTO, nullable=False),
        sa.Column("zona_texto", sa.String(), nullable=False),
        sa.Column("localidades", JSONB(), nullable=False),
        sa.Column("franjas", JSONB(), nullable=False),
        sa.Column("advertencias", JSONB(), nullable=False),
        sa.Column("cuerpo", sa.String(), nullable=True),
        sa.Column("cronograma", sa.String(), nullable=True),
        sa.Column("datos_crudos", JSONB(), nullable=False),
        sa.Column("primera_vez_visto", _MOMENTO, nullable=False),
        sa.Column("ultima_vez_visto", _MOMENTO, nullable=False),
    )
    op.create_table(
        "corte_dias",
        sa.Column(
            "articulo_id",
            sa.Integer(),
            sa.ForeignKey("cortes.articulo_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fecha", sa.Date(), primary_key=True),
    )
    op.create_index("ix_corte_dias_fecha", "corte_dias", ["fecha"])
    op.create_table(
        "zonas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("nombre_norm", sa.String(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("localidad_norm", sa.String(), nullable=False),
        sa.Column("veces_vista", sa.Integer(), nullable=False),
        sa.Column("primera_vez", _MOMENTO, nullable=False),
        sa.Column("ultima_vez", _MOMENTO, nullable=False),
        sa.UniqueConstraint("nombre_norm", "tipo", "localidad_norm"),
    )
    op.create_table(
        "suscripciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("canal", sa.String(), nullable=False),
        sa.Column("destino", sa.String(), nullable=False),
        sa.Column("palabras_clave", JSONB(), nullable=False),
        sa.Column("localidades_excluidas", JSONB(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("creada_en", _MOMENTO, nullable=False),
        sa.UniqueConstraint("canal", "destino"),
    )
    op.create_table(
        "notificaciones",
        sa.Column(
            "suscripcion_id",
            sa.Integer(),
            sa.ForeignKey("suscripciones.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "articulo_id",
            sa.Integer(),
            sa.ForeignKey("cortes.articulo_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fecha", sa.Date(), primary_key=True),
        sa.Column("enviada_en", _MOMENTO, nullable=False),
    )

    # Supabase publica el esquema "public" mediante una API con una clave anónima. Con RLS activo y
    # sin políticas, esa API no puede leer nada (ni los emails de las suscripciones), mientras que
    # el dueño de las tablas, el rol con el que se conecta esta aplicación, no se ve afectado.
    for tabla in (*_TABLAS, "alembic_version"):
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for tabla in reversed(_TABLAS):
        op.drop_table(tabla)

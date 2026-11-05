"""Pruebas del módulo único de autorización (portal.access).

Cubre: matriz de permisos por rol, superusuario sin Employee, usuario sin
Employee, rol inactivo, allowed_delegations por rol, delegación activa
inválida, regla de rango en visible_users/can_assign_role, la migración de
datos jefatura/usuario -> roles nuevos y el AuditLog en un 403.
"""
from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import path
from django.views import View

from operaciones.models import Employee
from portal.access import (
    ACTIVE_DELEGATION_KEY,
    ALL_DELEGATIONS,
    ModulePermissionMixin,
    can_assign_role,
    get_access,
    get_active_delegation,
    get_role,
    has_permission,
    allowed_delegations,
    permission_required,
    set_active_delegation,
    visible_users,
)
from portal.models import AuditLog
from sgr_core.models import Delegation, Role, RolePermission
from sgr_core.roles import ACTIONS, BASE_ROLES, MODULES, SCOPE_RANKS, ensure_base_roles

# Vistas de prueba: solo para estos tests; no son pantallas del proyecto
# ni agregan URLs a config/urls.py (se usa un ROOT_URLCONF de prueba).


class UsersListView(ModulePermissionMixin, View):
    module = 'users'
    action = 'view'

    def get(self, request):
        return HttpResponse('ok-cbv')


@permission_required('users', 'edit')
def users_edit_view(request):
    return HttpResponse('ok-fb')


urlpatterns = [
    path('test-acceso/usuarios/', UsersListView.as_view(), name='test_access_cbv'),
    path('test-acceso/usuarios/editar/', users_edit_view, name='test_access_fb'),
]

TEST_ROOT_URLCONF = 'portal.tests.test_access'


def _user(username, **kwargs):
    return User.objects.create_user(username=username, password='Demo2026!', **kwargs)


class AccessFixtureMixin:
    """Datos base: delegaciones DEL01-DEL07, roles base y usuarios de cada rol."""

    @classmethod
    def setUpTestData(cls):
        ensure_base_roles(Role, RolePermission)
        cls.roles = {role.code: role for role in Role.objects.all()}

        cls.d_centro = Delegation.objects.create(name='Centro', code='DEL01')
        cls.d_avenida = Delegation.objects.create(name='Avenida del Mar', code='DEL02')
        cls.d_antena = Delegation.objects.create(name='La Antena-La Florida', code='DEL03')
        cls.d_companias = Delegation.objects.create(name='Las Compañías', code='DEL04')
        cls.d_pampa = Delegation.objects.create(name='La Pampa', code='DEL05')
        cls.d_rural = Delegation.objects.create(name='Rural', code='DEL06')
        cls.d_inactiva = Delegation.objects.create(
            name='Cerrada', code='DEL07', status='Inactiva',
        )

        # Superusuario SIN Employee (rol virtual).
        cls.superuser = _user('superadmin', is_staff=True, is_superuser=True)

        # Coordinador con DEL01-DEL03 autorizadas.
        cls.coordinador = _user('coordinador')
        cls.emp_coordinador = Employee.objects.create(
            user=cls.coordinador, rut='11.111.111-1',
            delegation=cls.d_centro, role=cls.roles['ROL02'],
        )
        cls.emp_coordinador.authorized_delegations.set(
            [cls.d_centro, cls.d_avenida, cls.d_antena]
        )

        cls.delegado = _user('delegado')
        cls.emp_delegado = Employee.objects.create(
            user=cls.delegado, rut='22.222.222-2',
            delegation=cls.d_centro, role=cls.roles['ROL03'],
        )
        cls.funcionario = _user('funcionario')
        cls.emp_funcionario = Employee.objects.create(
            user=cls.funcionario, rut='33.333.333-3',
            delegation=cls.d_centro, role=cls.roles['ROL04'],
        )

        # Funcionario de DEL03 (dentro de las autorizadas del coordinador).
        cls.funcionario_antena = _user('funcionario.antena')
        cls.emp_funcionario_antena = Employee.objects.create(
            user=cls.funcionario_antena, rut='44.444.444-4',
            delegation=cls.d_antena, role=cls.roles['ROL04'],
        )

        # Delegado de DEL05 (fuera del contexto del coordinador).
        cls.delegado_pampa = _user('delegado.pampa')
        cls.emp_delegado_pampa = Employee.objects.create(
            user=cls.delegado_pampa, rut='55.555.555-5',
            delegation=cls.d_pampa, role=cls.roles['ROL03'],
        )

        # Coordinador SIN delegaciones autorizadas declaradas (base DEL05).
        cls.coordinador_sin_auth = _user('coordinador.sin')
        cls.emp_coordinador_sin_auth = Employee.objects.create(
            user=cls.coordinador_sin_auth, rut='66.666.666-6',
            delegation=cls.d_pampa, role=cls.roles['ROL02'],
        )

        cls.sin_empleado = _user('sin.empleado')

        # Empleado con rol Inactivo.
        cls.role_inactivo = Role.objects.create(
            code='ROL99', name='Rol inactivo de prueba',
            scope='own_delegation', status='Inactivo',
        )
        cls.rol_inactivo_user = _user('rol.inactivo')
        cls.emp_rol_inactivo = Employee.objects.create(
            user=cls.rol_inactivo_user, rut='77.777.777-7',
            delegation=cls.d_rural, role=cls.role_inactivo,
        )

    @staticmethod
    def all_combos():
        return [(module, action) for module, _ in MODULES for action, _ in ACTIONS]

    @staticmethod
    def expected_for(code):
        spec = next(spec for spec in BASE_ROLES if spec['code'] == code)
        return {
            (module, action)
            for module, actions in spec['permissions'].items()
            for action in actions
        }

# ------------------------------------------------------------
# 1) Matriz de permisos por rol (módulo x acción)
# ------------------------------------------------------------

class PermissionMatrixTests(AccessFixtureMixin, TestCase):

    def test_rango_derivado_del_alcance(self):
        for spec in BASE_ROLES:
            role = self.roles[spec['code']]
            self.assertEqual(role.rank, SCOPE_RANKS[role.scope])

    def test_matriz_superadministrador_todo(self):
        # Superusuario sin Employee: rol virtual con todos los permisos.
        for module, action in self.all_combos():
            self.assertTrue(
                has_permission(self.superuser, module, action),
                f'debía permitir {module}.{action}',
            )

    def _assert_matriz(self, user, code):
        esperado = self.expected_for(code)
        for module, action in self.all_combos():
            with self.subTest(rol=code, modulo=module, accion=action):
                self.assertEqual(
                    has_permission(user, module, action),
                    (module, action) in esperado,
                )

    def test_matriz_coordinador(self):
        self._assert_matriz(self.coordinador, 'ROL02')

    def test_matriz_delegado(self):
        self._assert_matriz(self.delegado, 'ROL03')

    def test_matriz_funcionario(self):
        self._assert_matriz(self.funcionario, 'ROL04')

    def test_los_cuatro_roles_base_existen_y_estan_activos(self):
        codes = set(Role.objects.filter(code__in=['ROL01', 'ROL02', 'ROL03', 'ROL04'])
                    .values_list('code', flat=True))
        self.assertEqual(codes, {'ROL01', 'ROL02', 'ROL03', 'ROL04'})
        self.assertTrue(
            Role.objects.filter(code='ROL01', is_system=True, scope='all').exists()
        )
        self.assertFalse(
            Role.objects.filter(code__in=['ROL02', 'ROL03', 'ROL04'], is_system=True).exists()
        )


# ------------------------------------------------------------
# 2) get_role: superuser sin Employee, sin Employee, rol inactivo
# ------------------------------------------------------------

class GetRoleEdgeTests(AccessFixtureMixin, TestCase):

    def test_superuser_sin_employee_tiene_rol_virtual(self):
        self.assertFalse(hasattr(self.superuser, 'employee') and
                        Employee.objects.filter(user=self.superuser).exists())
        role = get_role(self.superuser)
        self.assertIsNotNone(role)
        self.assertTrue(role.is_virtual)
        self.assertEqual(role.scope, 'all')
        self.assertEqual(role.rank, 3)

    def test_usuario_sin_employee_sin_acceso(self):
        self.assertIsNone(get_role(self.sin_empleado))
        self.assertFalse(has_permission(self.sin_empleado, 'attentions', 'view'))
        self.assertEqual(allowed_delegations(self.sin_empleado), [])
        self.assertFalse(can_assign_role(self.sin_empleado, self.roles['ROL04']))
        self.assertEqual(visible_users(self.sin_empleado).count(), 0)

    def test_rol_inactivo_sin_acceso(self):
        role = get_role(self.rol_inactivo_user)
        self.assertIsNone(role)
        self.assertFalse(has_permission(self.rol_inactivo_user, 'attentions', 'view'))
        self.assertEqual(allowed_delegations(self.rol_inactivo_user), [])
        self.assertEqual(visible_users(self.rol_inactivo_user).count(), 0)

    def test_anonimo_sin_acceso(self):
        self.assertIsNone(get_role(AnonymousUser()))
        self.assertIsNone(get_role(None))
        self.assertFalse(has_permission(AnonymousUser(), 'attentions', 'view'))

    def test_get_role_devuelve_los_datos_del_rol(self):
        role = get_role(self.delegado)
        self.assertEqual(role.code, 'ROL03')
        self.assertEqual(role.scope, 'own_delegation')
        self.assertEqual(role.rank, 1)
        self.assertFalse(role.is_virtual)


# ------------------------------------------------------------
# 3) allowed_delegations por rol
# ------------------------------------------------------------

class AllowedDelegationsTests(AccessFixtureMixin, TestCase):

    def _codes(self, delegations):
        return sorted(d.code for d in delegations)

    def test_superadmin_todas_las_activas(self):
        codes = self._codes(allowed_delegations(self.superuser))
        self.assertEqual(codes, ['DEL01', 'DEL02', 'DEL03', 'DEL04', 'DEL05', 'DEL06'])
        self.assertNotIn('DEL07', codes)  # inactiva no se incluye

    def test_coordinador_sus_autorizadas(self):
        self.assertEqual(
            self._codes(allowed_delegations(self.coordinador)),
            ['DEL01', 'DEL02', 'DEL03'],
        )

    def test_coordinador_sin_autorizadas_usa_su_delegacion(self):
        self.assertEqual(
            self._codes(allowed_delegations(self.coordinador_sin_auth)),
            ['DEL05'],
        )

    def test_delegado_y_funcionario_solo_su_delegacion(self):
        self.assertEqual(self._codes(allowed_delegations(self.delegado)), ['DEL01'])
        self.assertEqual(self._codes(allowed_delegations(self.funcionario)), ['DEL01'])
        self.assertEqual(
            self._codes(allowed_delegations(self.emp_delegado_pampa.user)), ['DEL05'],
        )

    def test_empleado_con_scope_all_ve_las_activas(self):
        emp = Employee.objects.create(
            user=_user('super.empleado'), rut='88.888.888-8',
            delegation=self.d_centro, role=self.roles['ROL01'],
        )
        user = emp.user
        self.assertEqual(
            self._codes(allowed_delegations(user)),
            ['DEL01', 'DEL02', 'DEL03', 'DEL04', 'DEL05', 'DEL06'],
        )

    def test_employee_allowed_delegations_metodo(self):
        self.assertEqual(
            self._codes(self.emp_coordinador.allowed_delegations()),
            ['DEL01', 'DEL02', 'DEL03'],
        )
        self.assertEqual(
            self._codes(self.emp_delegado.allowed_delegations()), ['DEL01'],
        )

# ------------------------------------------------------------
# 4) Delegación activa en sesión (get/set con validación)
# ------------------------------------------------------------

class ActiveDelegationTests(AccessFixtureMixin, TestCase):

    def _request(self, user, session=None):
        request = RequestFactory().get('/')
        request.user = user
        request.session = session if session is not None else {}
        return request

    def test_superadmin_por_defecto_all(self):
        request = self._request(self.superuser)
        self.assertEqual(get_active_delegation(request), ALL_DELEGATIONS)

    def test_coordinador_por_defecto_primera_autorizada(self):
        request = self._request(self.coordinador)
        activa = get_active_delegation(request)
        self.assertIsNotNone(activa)
        self.assertEqual(activa.code, 'DEL01')

    def test_resto_por_defecto_su_delegacion(self):
        for user, code in ((self.delegado, 'DEL01'), (self.funcionario, 'DEL01')):
            activa = get_active_delegation(self._request(user))
            self.assertIsNotNone(activa)
            self.assertEqual(activa.code, code)

    def test_set_valido_persiste_y_get_lo_devuelve(self):
        request = self._request(self.coordinador)
        self.assertTrue(set_active_delegation(request, self.d_antena.pk))
        activa = get_active_delegation(request)
        self.assertEqual(activa.pk, self.d_antena.pk)

    def test_set_delegacion_no_autorizada_rechazada(self):
        request = self._request(self.coordinador)
        self.assertTrue(set_active_delegation(request, self.d_avenida.pk))
        antes = dict(request.session)
        # DEL04 no está entre las autorizadas del coordinador.
        self.assertFalse(set_active_delegation(request, self.d_companias.pk))
        self.assertEqual(dict(request.session), antes)

    def test_set_all_rechazado_para_no_alcance_all(self):
        request = self._request(self.coordinador)
        self.assertFalse(set_active_delegation(request, ALL_DELEGATIONS))
        request = self._request(self.delegado)
        self.assertFalse(set_active_delegation(request, ALL_DELEGATIONS))
        request = self._request(self.superuser)
        self.assertTrue(set_active_delegation(request, ALL_DELEGATIONS))

    def test_delegado_no_puede_elegir_otra_delegacion(self):
        request = self._request(self.delegado)
        self.assertFalse(set_active_delegation(request, self.d_pampa.pk))

    def test_valor_invalido_en_sesion_cae_al_defecto(self):
        for invalido in ('999999', 'basura', ''):
            request = self._request(
                self.delegado, session={ACTIVE_DELEGATION_KEY: invalido},
            )
            activa = get_active_delegation(request)
            self.assertIsNotNone(activa)
            self.assertEqual(activa.code, 'DEL01', f'valor {invalido!r}')

    def test_all_en_sesion_de_usuario_sin_alcance_all_se_ignora(self):
        request = self._request(
            self.coordinador, session={ACTIVE_DELEGATION_KEY: ALL_DELEGATIONS},
        )
        activa = get_active_delegation(request)
        self.assertIsNotNone(activa)
        self.assertEqual(activa.code, 'DEL01')

    def test_sin_acceso_no_tiene_delegacion_activa(self):
        request = self._request(self.sin_empleado)
        self.assertIsNone(get_active_delegation(request))
        self.assertFalse(set_active_delegation(request, self.d_centro.pk))

# ------------------------------------------------------------
# 5) Regla de rango: visible_users y can_assign_role
# ------------------------------------------------------------

class RankRulesTests(AccessFixtureMixin, TestCase):

    def _visible(self, user):
        return set(visible_users(user).values_list('username', flat=True))

    def test_superusuario_ve_a_todos_incluidos_superusuarios(self):
        otro_super = _user('superadmin2', is_superuser=True, is_staff=True)
        visibles = self._visible(self.superuser)
        self.assertIn(otro_super.username, visibles)
        self.assertIn(self.superuser.username, visibles)
        self.assertEqual(visibles, set(User.objects.values_list('username', flat=True)))

    def test_superusuario_no_visible_para_no_superusuario(self):
        for user in (self.coordinador, self.delegado, self.funcionario):
            self.assertNotIn('superadmin', self._visible(user), user.username)

    def test_coordinador_ve_menor_rango_en_sus_autorizadas(self):
        self.assertEqual(
            self._visible(self.coordinador),
            {'delegado', 'funcionario', 'funcionario.antena'},
        )

    def test_coordinador_sin_autorizadas_ve_solo_su_delegacion(self):
        self.assertEqual(
            self._visible(self.coordinador_sin_auth),
            {'delegado.pampa'},
        )

    def test_delegado_ve_solo_funcionarios_de_su_delegacion(self):
        self.assertEqual(self._visible(self.delegado), {'funcionario'})
        # No ve a otro delegado (mismo rango) ni de otra delegación.
        self.assertNotIn('delegado.pampa', self._visible(self.delegado))
        self.assertNotIn('funcionario.antena', self._visible(self.delegado))

    def test_funcionario_no_ve_a_nadie(self):
        self.assertEqual(self._visible(self.funcionario), set())

    def test_usuarios_sin_employee_no_visibles(self):
        self.assertNotIn('sin.empleado', self._visible(self.coordinador))
        self.assertNotIn('rol.inactivo', self._visible(self.coordinador))

    def test_can_assign_role_regla_de_rango(self):
        roles = self.roles
        # Superusuario: asigna todo (menos roles Inactivos).
        for code in ('ROL01', 'ROL02', 'ROL03', 'ROL04'):
            self.assertTrue(can_assign_role(self.superuser, roles[code]), code)
        self.assertFalse(can_assign_role(self.superuser, self.role_inactivo))

        # Coordinador (rango 2): asigna rango menor; no su igual ni sistema.
        self.assertTrue(can_assign_role(self.coordinador, roles['ROL03']))
        self.assertTrue(can_assign_role(self.coordinador, roles['ROL04']))
        self.assertFalse(can_assign_role(self.coordinador, roles['ROL02']))
        self.assertFalse(can_assign_role(self.coordinador, roles['ROL01']))
        self.assertFalse(can_assign_role(self.coordinador, self.role_inactivo))

        # Delegado (rango 1): solo funcionario.
        self.assertTrue(can_assign_role(self.delegado, roles['ROL04']))
        self.assertFalse(can_assign_role(self.delegado, roles['ROL03']))
        self.assertFalse(can_assign_role(self.delegado, roles['ROL02']))
        self.assertFalse(can_assign_role(self.delegado, roles['ROL01']))

        # Funcionario (rango 0): no asigna ningún rol.
        for code in ('ROL01', 'ROL02', 'ROL03', 'ROL04'):
            self.assertFalse(can_assign_role(self.funcionario, roles[code]), code)

        # Sin acceso / rol destino None.
        self.assertFalse(can_assign_role(self.sin_empleado, roles['ROL04']))
        self.assertFalse(can_assign_role(self.delegado, None))

    def test_employee_clean_rechaza_autorizadas_ajenas_en_own_scopes(self):
        emp = Employee.objects.create(
            user=_user('limpio.pampa'), rut='99.999.999-9',
            delegation=self.d_pampa, role=self.roles['ROL03'],
        )
        emp.authorized_delegations.set([self.d_pampa])
        emp.full_clean()  # su propia delegación: permitida

        emp.authorized_delegations.set([self.d_pampa, self.d_centro])
        with self.assertRaises(ValidationError):
            emp.full_clean()

# ------------------------------------------------------------
# 6) ModulePermissionMixin / permission_required: 403 + AuditLog
# ------------------------------------------------------------

@override_settings(ROOT_URLCONF=TEST_ROOT_URLCONF)
class AccessDeniedAuditTests(AccessFixtureMixin, TestCase):

    def _ultimo_log(self):
        return AuditLog.objects.filter(action='access_denied').first()

    def test_cbv_sin_permiso_devuelve_403_y_audita(self):
        self.client.force_login(self.funcionario)
        resp = self.client.get('/test-acceso/usuarios/')
        self.assertEqual(resp.status_code, 403)
        log = self._ultimo_log()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.funcionario)
        self.assertEqual(log.module, 'users')
        self.assertIn('/test-acceso/usuarios/', log.detail)
        self.assertTrue(log.ip)

    def test_cbv_con_permiso_devuelve_200_sin_auditar(self):
        self.client.force_login(self.coordinador)
        resp = self.client.get('/test-acceso/usuarios/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'ok-cbv')
        self.assertFalse(AuditLog.objects.filter(action='access_denied').exists())

    def test_decorador_sin_permiso_devuelve_403_y_audita(self):
        self.client.force_login(self.funcionario)
        resp = self.client.get('/test-acceso/usuarios/editar/')
        self.assertEqual(resp.status_code, 403)
        log = self._ultimo_log()
        self.assertIsNotNone(log)
        self.assertEqual(log.module, 'users')
        self.assertIn('users.edit', log.detail)

        self.client.logout()
        self.client.force_login(self.delegado)
        resp = self.client.get('/test-acceso/usuarios/editar/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'ok-fb')

    def test_sin_employee_devuelve_403_y_audita(self):
        self.client.force_login(self.sin_empleado)
        resp = self.client.get('/test-acceso/usuarios/')
        self.assertEqual(resp.status_code, 403)
        log = self._ultimo_log()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.sin_empleado)

    def test_superuser_devuelve_200(self):
        self.client.force_login(self.superuser)
        resp = self.client.get('/test-acceso/usuarios/')
        self.assertEqual(resp.status_code, 200)

    def test_anonimo_devuelve_403(self):
        resp = self.client.get('/test-acceso/usuarios/')
        self.assertEqual(resp.status_code, 403)
        log = self._ultimo_log()
        self.assertIsNotNone(log)
        self.assertIsNone(log.user)

    def test_permisos_resueltos_una_vez_por_request(self):
        user = User.objects.get(username='coordinador')
        request = RequestFactory().get('/')
        request.user = user
        # employee + rol + permisos de Django (directos del usuario y de sus
        # grupos): 4 consultas, una sola vez por request.
        with self.assertNumQueries(4):
            first = get_access(request)
        with self.assertNumQueries(0):
            second = get_access(request)
            self.assertTrue(second.can('users', 'view'))
        self.assertIs(first, second)

        # Una request nueva resuelve sus permisos de nuevo (sin cache de proceso).
        # Se usa una instancia fresca de usuario: la instancia anterior ya tiene
        # employee/role en cache del ORM y solo haría 1 consulta.
        otra = RequestFactory().get('/')
        otra.user = User.objects.get(username='coordinador')
        with self.assertNumQueries(4):
            tercero = get_access(otra)
        self.assertIsNot(first, tercero)

# ------------------------------------------------------------
# 7) Migración de datos: jefatura/usuario -> roles nuevos
# ------------------------------------------------------------

class LegacyRoleDataMigrationTests(TransactionTestCase):
    """Aplica la migración sobre datos de ejemplo con el esquema viejo."""

    migrate_from = [('operaciones', '0003_employee_role_task_assigned_to')]
    migrate_to = [('operaciones', '0006_employee_role_final')]

    def tearDown(self):
        # Siempre dejar la base en el estado más reciente.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migracion_datos_jefatura_usuario(self):
        delegacion = Delegation.objects.create(name='Los Nogales', code='DEL08')
        boss_u = User.objects.create_user('legacy.jefatura', password='x')
        user_u = User.objects.create_user('legacy.usuario', password='x')
        otro_u = User.objects.create_user('legacy.otro', password='x')

        # 1) Retroceso al esquema anterior (role era CharField).
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)

        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldEmployee = old_apps.get_model('operaciones', 'Employee')
        OldUser = old_apps.get_model('auth', 'User')
        OldDelegation = old_apps.get_model('sgr_core', 'Delegation')
        del_old = OldDelegation.objects.get(pk=delegacion.pk)
        OldEmployee.objects.create(
            user=OldUser.objects.get(pk=boss_u.pk),
            rut='30.000.001-1', delegation=del_old, role='jefatura',
        )
        OldEmployee.objects.create(
            user=OldUser.objects.get(pk=user_u.pk),
            rut='30.000.002-2', delegation=del_old, role='usuario',
        )
        OldEmployee.objects.create(
            user=OldUser.objects.get(pk=otro_u.pk),
            rut='30.000.003-3', delegation=del_old, role='desconocido',
        )

        # 2) Avance hasta el cierre de la migración (incluye la de datos).
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)

        # 3) Verificación con los modelos reales.
        self.assertEqual(Employee.objects.get(user=boss_u).role.code, 'ROL03')
        self.assertEqual(Employee.objects.get(user=user_u).role.code, 'ROL04')
        # Valor desconocido: mapeo defensivo a funcionario.
        self.assertEqual(Employee.objects.get(user=otro_u).role.code, 'ROL04')

        # Los roles base existen (los crea la migración de datos de sgr_core).
        codes = set(Role.objects.filter(
            code__in=['ROL01', 'ROL02', 'ROL03', 'ROL04'],
        ).values_list('code', flat=True))
        self.assertEqual(codes, {'ROL01', 'ROL02', 'ROL03', 'ROL04'})

        # Re-ejecutar hacia adelante no cambia nada (idempotente).
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.assertEqual(Employee.objects.get(user=boss_u).role.code, 'ROL03')
        self.assertEqual(Employee.objects.get(user=user_u).role.code, 'ROL04')

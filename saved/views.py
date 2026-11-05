from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from credit_cards.models import CreditCard
from saved import services
from saved.constants import (
    MAX_SAVED_SCENARIOS_PER_USER,
    MAX_SAVED_SEARCHES_PER_USER,
)
from saved.models import (
    Collection,
    SavedComparison,
    SavedComparisonItem,
    SavedScenario,
    SavedSearch,
)
from saved.serializers import (
    CollectionCardAddSerializer,
    CollectionSerializer,
    PublicCollectionSerializer,
    PublicSavedComparisonSerializer,
    SavedComparisonSerializer,
    SavedScenarioSerializer,
    SavedSearchImportSerializer,
    SavedSearchSerializer,
    ShortlistAddSerializer,
    ShortlistImportSerializer,
    ShortlistItemSerializer,
)


def _ordered_items_prefetch(public_only=False):
    """Prefetch comparison items in position order with their cards loaded.

    Parameters
    ----------
    public_only : bool
        When True, only include items whose card is public (verified and active).
        Used by public share endpoints to prevent draft cards from being loaded.

    Returns
    -------
    Prefetch
        Prefetch for the ``items`` relation of SavedComparison
    """
    queryset = SavedComparisonItem.objects.select_related("card__bank").order_by(
        "position"
    )
    if public_only:
        queryset = queryset.filter(card__in=CreditCard.objects.public())
    return Prefetch(
        "items",
        queryset=queryset,
    )


@extend_schema_view(
    list=extend_schema(tags=["saved"], summary="List my saved comparisons"),
    create=extend_schema(tags=["saved"], summary="Save a comparison"),
    retrieve=extend_schema(tags=["saved"], summary="Get one of my saved comparisons"),
    update=extend_schema(tags=["saved"], summary="Replace a saved comparison"),
    partial_update=extend_schema(tags=["saved"], summary="Edit a saved comparison"),
    destroy=extend_schema(tags=["saved"], summary="Delete a saved comparison"),
)
@method_decorator(never_cache, name="dispatch")
class SavedComparisonViewSet(viewsets.ModelViewSet):
    """CRUD for the requesting user's saved comparisons.

    Objects owned by other users are not visible here and return 404.
    """

    serializer_class = SavedComparisonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only the requesting user's comparisons, newest first.

        Parameters
        ----------
        None

        Returns
        -------
        QuerySet of SavedComparison
            Comparisons owned by the requesting user
        """
        if getattr(self, "swagger_fake_view", False):
            return SavedComparison.objects.none()
        return (
            SavedComparison.objects.filter(user=self.request.user)
            .prefetch_related(_ordered_items_prefetch())
            .order_by("-modified", "-id")
        )

    @extend_schema(
        tags=["saved"],
        summary="Duplicate a saved comparison",
        request=None,
        responses={201: SavedComparisonSerializer},
    )
    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """Copy one of my comparisons into a new private comparison.

        Parameters
        ----------
        request : Request
            The authenticated request
        pk : str
            Primary key of the source comparison

        Returns
        -------
        Response
            201 with the new comparison
        """
        source = self.get_object()
        copy = services.duplicate_comparison(request.user, source)
        serializer = self.get_serializer(copy)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["saved"], summary="List my collections"),
    create=extend_schema(tags=["saved"], summary="Create a collection"),
    retrieve=extend_schema(tags=["saved"], summary="Get one of my collections"),
    update=extend_schema(tags=["saved"], summary="Replace a collection"),
    partial_update=extend_schema(tags=["saved"], summary="Edit a collection"),
    destroy=extend_schema(tags=["saved"], summary="Delete a collection"),
)
@method_decorator(never_cache, name="dispatch")
class CollectionViewSet(viewsets.ModelViewSet):
    """CRUD for the requesting user's collections, plus card add and remove.

    Objects owned by other users are not visible here and return 404.
    """

    serializer_class = CollectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only the requesting user's collections, newest first.

        Parameters
        ----------
        None

        Returns
        -------
        QuerySet of Collection
            Collections owned by the requesting user
        """
        if getattr(self, "swagger_fake_view", False):
            return Collection.objects.none()
        return (
            Collection.objects.filter(user=self.request.user)
            .prefetch_related("items__card__bank")
            .order_by("-modified", "-id")
        )

    @extend_schema(
        tags=["saved"],
        summary="Add a card to a collection",
        request=CollectionCardAddSerializer,
        responses={201: CollectionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="cards")
    def add_card(self, request, pk=None):
        """Add a card, with optional notes, to one of my collections.

        Parameters
        ----------
        request : Request
            Body with card_id and optional notes
        pk : str
            Primary key of the collection

        Returns
        -------
        Response
            201 with the updated collection
        """
        collection = self.get_object()
        serializer = CollectionCardAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_card_to_collection(
            collection,
            serializer.validated_data["card_id"],
            serializer.validated_data["notes"],
        )
        collection = self.get_object()
        return Response(
            CollectionSerializer(collection, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["saved"],
        summary="Remove a card from a collection",
        request=None,
        parameters=[
            OpenApiParameter("card_id", OpenApiTypes.INT, OpenApiParameter.PATH),
        ],
        responses={204: None},
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"cards/(?P<card_id>[0-9]+)",
    )
    def remove_card(self, request, pk=None, card_id=None):
        """Remove a card from one of my collections.

        Parameters
        ----------
        request : Request
            The authenticated request
        pk : str
            Primary key of the collection
        card_id : str
            Primary key of the card to remove

        Returns
        -------
        Response
            204 when removed; 404 when the card is not in the collection
        """
        collection = self.get_object()
        services.remove_card_from_collection(collection, int(card_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["saved"],
    summary="Read a shared comparison (public, no auth)",
    responses={200: PublicSavedComparisonSerializer},
    auth=[{}],
)
@method_decorator(never_cache, name="dispatch")
class SharedComparisonView(APIView):
    """Public read-only view of a comparison that its owner has made public.

    Anonymous access. Returns 404 for unknown tokens and for comparisons that
    are not public, so a revoked link stops working immediately.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        """Return a public comparison by its share token.

        Parameters
        ----------
        request : Request
            The anonymous request
        token : str
            The comparison's share_token

        Returns
        -------
        Response
            200 with the comparison content, without owner identity
        """
        comparison = get_object_or_404(
            SavedComparison.objects.filter(is_public=True).prefetch_related(
                _ordered_items_prefetch(public_only=True)
            ),
            share_token=token,
        )
        serializer = PublicSavedComparisonSerializer(
            comparison,
            context={"request": request},
        )
        return Response(serializer.data)


@extend_schema(
    tags=["saved"],
    summary="Read a public collection by slug (public, no auth)",
    responses={200: PublicCollectionSerializer},
    auth=[{}],
)
@method_decorator(never_cache, name="dispatch")
class SharedCollectionView(APIView):
    """Public read-only view of a collection its owner has made public.

    Anonymous access. Returns 404 for unknown slugs and for private
    collections.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        """Return a public collection by its slug.

        Parameters
        ----------
        request : Request
            The anonymous request
        slug : str
            The collection's slug

        Returns
        -------
        Response
            200 with the collection content, without owner identity
        """
        collection = get_object_or_404(
            Collection.objects.filter(is_public=True).prefetch_related(
                "items__card__bank"
            ),
            slug=slug,
        )
        serializer = PublicCollectionSerializer(
            collection,
            context={"request": request},
        )
        return Response(serializer.data)


# --- Shortlist, saved searches, saved scenarios (redesign Phase 3) ---------


@method_decorator(never_cache, name="dispatch")
class ShortlistView(APIView):
    """The requesting user's cross-device shortlist.

    GET returns the whole shortlist (capped at 4 per vertical by the add
    path, so the payload is bounded). POST adds one product idempotently:
    201 when created, 200 when it was already shortlisted.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ShortlistItemSerializer

    @extend_schema(
        tags=["saved"],
        summary="List my shortlist",
        responses={200: ShortlistItemSerializer(many=True)},
    )
    def get(self, request):
        items = services.shortlist_items_for(request.user)
        return Response({"results": ShortlistItemSerializer(items, many=True).data})

    @extend_schema(
        tags=["saved"],
        summary="Add a product to my shortlist",
        request=ShortlistAddSerializer,
        responses={201: ShortlistItemSerializer, 200: ShortlistItemSerializer},
    )
    def post(self, request):
        serializer = ShortlistAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, created = services.add_shortlist_item(
            request.user,
            serializer.validated_data["vertical"],
            serializer.validated_data["key"],
        )
        item = services.shortlist_items_for(request.user).get(pk=item.pk)
        return Response(
            ShortlistItemSerializer(item).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@method_decorator(never_cache, name="dispatch")
class ShortlistImportView(APIView):
    """Merge an on-device shortlist into the server shortlist.

    Idempotent by construction (see services.import_shortlist_items):
    re-running it changes nothing, so clients may call it on every
    sign-in without a client-side "already imported" flag.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ShortlistImportSerializer

    @extend_schema(
        tags=["saved"],
        summary="Import an on-device shortlist into my server shortlist",
        request=ShortlistImportSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        serializer = ShortlistImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        imported, skipped = services.import_shortlist_items(
            request.user, serializer.validated_data["items"]
        )
        items = services.shortlist_items_for(request.user)
        return Response(
            {
                "imported": imported,
                "skipped": skipped,
                "results": ShortlistItemSerializer(items, many=True).data,
            }
        )


@method_decorator(never_cache, name="dispatch")
class ShortlistItemView(APIView):
    """Remove one product from the requesting user's shortlist (204 always)."""

    permission_classes = [IsAuthenticated]
    serializer_class = ShortlistItemSerializer

    @extend_schema(
        tags=["saved"],
        summary="Remove a product from my shortlist",
        responses={204: None},
    )
    def delete(self, request, vertical, key):
        services.remove_shortlist_item(request.user, vertical, key)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(tags=["saved"], summary="List my saved searches"),
    create=extend_schema(tags=["saved"], summary="Save a search"),
    retrieve=extend_schema(tags=["saved"], summary="Get one of my saved searches"),
    update=extend_schema(tags=["saved"], summary="Replace a saved search"),
    partial_update=extend_schema(tags=["saved"], summary="Edit a saved search"),
    destroy=extend_schema(tags=["saved"], summary="Delete a saved search"),
)
@method_decorator(never_cache, name="dispatch")
class SavedSearchViewSet(viewsets.ModelViewSet):
    """CRUD for the requesting user's saved searches. Others' rows 404."""

    serializer_class = SavedSearchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SavedSearch.objects.none()
        return SavedSearch.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        services._enforce_limit(
            SavedSearch.objects.filter(user=self.request.user),
            MAX_SAVED_SEARCHES_PER_USER,
            "saved searches",
        )
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        # Saving the identical search again returns the existing row with
        # 200 instead of tripping the (user, name, path, query) unique
        # constraint — a save is idempotent, like the import path.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        existing = SavedSearch.objects.filter(
            user=request.user,
            name=serializer.validated_data["name"],
            path=serializer.validated_data["path"],
            query=serializer.validated_data.get("query", ""),
        ).first()
        if existing is not None:
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # Renaming a search onto the exact (name, path, query) of another
        # of the user's rows trips the unique constraint; create treats
        # that collision idempotently, so update answers it with a clean
        # 400 instead of letting the IntegrityError surface as a 500.
        # The atomic block gives the failed save a savepoint to roll
        # back to, leaving the connection usable for the 400 response.
        # (partial_update delegates to update in DRF, so PATCH is
        # covered by this override too.)
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {
                    "detail": (
                        "Another of your saved searches already has that "
                        "name, path and query."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @extend_schema(
        tags=["saved"],
        summary="Import on-device saved searches (de-duplicated)",
        request=SavedSearchImportSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["post"], url_path="import")
    def import_searches(self, request):
        """Merge on-device searches; identical (name, path, query) rows are
        recognised by the model's unique constraint and skipped, so the
        import is idempotent without a client-side flag."""
        serializer = SavedSearchImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        imported = 0
        skipped = 0
        for entry in serializer.validated_data["searches"]:
            _, created = SavedSearch.objects.get_or_create(
                user=request.user,
                name=entry["name"],
                path=entry["path"],
                query=entry.get("query", ""),
            )
            if created:
                imported += 1
            else:
                skipped += 1
        results = SavedSearchSerializer(self.get_queryset(), many=True).data
        return Response({"imported": imported, "skipped": skipped, "results": results})


@extend_schema_view(
    list=extend_schema(tags=["saved"], summary="List my saved scenarios"),
    create=extend_schema(tags=["saved"], summary="Save a Plan scenario"),
    retrieve=extend_schema(tags=["saved"], summary="Get one of my saved scenarios"),
    update=extend_schema(tags=["saved"], summary="Replace a saved scenario"),
    partial_update=extend_schema(tags=["saved"], summary="Edit a saved scenario"),
    destroy=extend_schema(tags=["saved"], summary="Delete a saved scenario"),
)
@method_decorator(never_cache, name="dispatch")
class SavedScenarioViewSet(viewsets.ModelViewSet):
    """CRUD for the requesting user's saved Plan scenarios. Others' rows 404."""

    serializer_class = SavedScenarioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SavedScenario.objects.none()
        return SavedScenario.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        services._enforce_limit(
            SavedScenario.objects.filter(user=self.request.user),
            MAX_SAVED_SCENARIOS_PER_USER,
            "saved scenarios",
        )
        serializer.save(user=self.request.user)
